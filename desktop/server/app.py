# Локальный сервер приложения.
# Слушает только 127.0.0.1 на случайном порту, требует токен и проверяет Origin.
# Задачу выполняет отдельный процесс worker.py, поэтому «Стоп» убивает только его.

import asyncio
import json
import os
import secrets
import socket
import sys
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RENDERER_DIR = Path(__file__).resolve().parents[1] / "renderer"
WORKER_PATH = Path(__file__).with_name("worker.py")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


class TaskIn(BaseModel):
    task: str = ""


class ConfirmIn(BaseModel):
    id: str = ""
    action: str = ""
    text: str = ""


@dataclass
class TaskState:
    task: str
    proc: asyncio.subprocess.Process | None = None
    stderr: deque = field(default_factory=lambda: deque(maxlen=40))
    stderr_task: asyncio.Task | None = None
    pending_id: str | None = None
    last_usage: dict = field(default_factory=dict)
    last_step: int = 0
    stopped: bool = False
    started: bool = False
    remembered: bool = False
    final: dict | None = None


def _history_path() -> Path:
    override = os.environ.get("JARVIS_HISTORY_FILE")
    return Path(override) if override else PROJECT_ROOT / "data" / "history.json"


def _budget_limit() -> float:
    try:
        return max(0.0, float(os.environ.get("BUDGET_LIMIT_RUB", "500")))
    except ValueError:
        return 500.0


def _load_history() -> list[dict]:
    path = _history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        return []
    return [item for item in tasks if isinstance(item, dict)]


def _save_history(tasks: list[dict]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"tasks": tasks[:100]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


def _spent_rub(tasks: list[dict]) -> float:
    total = 0.0
    for item in tasks:
        try:
            total += float(item.get("cost") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _format_sse(event: dict) -> str:
    name = str(event.get("type") or "message")
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"event: {name}\ndata: {data}\n\n"


async def _drain_stderr(stream, sink: deque) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            return
        sink.append(line.decode("utf-8", "replace").rstrip())


async def _write_command(proc: asyncio.subprocess.Process, payload: dict) -> None:
    if proc.stdin is None or proc.returncode is not None:
        raise RuntimeError("Воркер уже завершился.")
    proc.stdin.write(
        (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    )
    await proc.stdin.drain()


async def _terminate(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    with suppress(ProcessLookupError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except (asyncio.TimeoutError, ProcessLookupError):
        with suppress(ProcessLookupError):
            proc.kill()
        with suppress(Exception):
            await proc.wait()


def create_app(token: str, port: int, test_worker: bool = False) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.port = port
    app.state.origin = f"http://127.0.0.1:{port}"
    app.state.host = f"127.0.0.1:{port}"
    app.state.test_worker = test_worker
    app.state.active = None
    app.state.active_lock = asyncio.Lock()
    app.state.history_lock = asyncio.Lock()

    async def remember(state: TaskState) -> dict:
        usage = state.last_usage or {}
        final = state.final or {}
        async with app.state.history_lock:
            tasks = _load_history()
            cost = float(final.get("cost") or usage.get("cost") or 0)
            entry = {
                "id": uuid.uuid4().hex[:10],
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "task": state.task,
                "answer": str(final.get("answer") or ""),
                "steps": int(final.get("steps") or usage.get("step") or 0),
                "tokens": int(final.get("tokens") or usage.get("tokens") or 0),
                "cost": round(cost, 4),
                "stopped_reason": str(final.get("stopped_reason") or "error"),
            }
            tasks.insert(0, entry)
            _save_history(tasks)
            limit = _budget_limit()
            remaining = max(0.0, limit - _spent_rub(tasks))
            entry["budget_limit"] = limit
            entry["remaining_rub"] = remaining
        state.remembered = True
        if state.final is not None:
            state.final["remaining_rub"] = remaining
        return entry

    async def finish(state: TaskState) -> None:
        await _terminate(state.proc)
        if state.stderr_task is not None:
            state.stderr_task.cancel()
            with suppress(Exception):
                await state.stderr_task
        if state.started and not state.remembered:
            if state.stopped:
                answer = "Задача остановлена: окно закрыло соединение с сервером."
                reason = "cancelled"
            else:
                answer = "Задача прервана: соединение с окном закрылось."
                reason = "cancelled"
            state.final = {
                "type": "final",
                "answer": answer,
                "steps": int(state.last_usage.get("step") or 0),
                "tokens": int(state.last_usage.get("tokens") or 0),
                "cost": float(state.last_usage.get("cost") or 0),
                "stopped_reason": reason,
            }
            with suppress(Exception):
                await remember(state)
        async with app.state.active_lock:
            if app.state.active is state:
                app.state.active = None

    async def events(state: TaskState):
        assert state.proc is not None and state.proc.stdout is not None
        while True:
            try:
                line = await asyncio.wait_for(
                    state.proc.stdout.readline(), timeout=15
                )
            except asyncio.TimeoutError:
                yield {"type": "ping"}
                continue
            if not line:
                return
            try:
                event = json.loads(line.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "confirm":
                state.pending_id = event.get("id")
            elif kind == "step":
                with suppress(TypeError, ValueError):
                    state.last_step = int(event.get("step") or 0)
            elif kind == "usage":
                state.last_usage = event
            elif kind == "final":
                state.pending_id = None
                state.final = event
            yield event
            if kind == "final":
                return

    async def start_worker(state: TaskState) -> None:
        args = [sys.executable, str(WORKER_PATH)]
        if test_worker:
            args.append("--selftest")
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("JARVIS_TOKEN", "JARVIS_TEST_WORKER")
        }
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        state.proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        state.started = True
        state.stderr_task = asyncio.create_task(
            _drain_stderr(state.proc.stderr, state.stderr)
        )
        await _write_command(state.proc, {"type": "run", "task": state.task})

    def cancelled_event(state: TaskState) -> dict:
        usage = state.last_usage or {}
        if state.stopped:
            answer = "Остановлено пользователем."
            reason = "cancelled"
        else:
            code = state.proc.returncode if state.proc else "?"
            tail = ""
            if state.stderr:
                tail = "\n\nПоследние строки лога:\n" + "\n".join(
                    list(state.stderr)[-5:]
                )
            answer = f"Воркер завершился неожиданно (код {code}).{tail}"
            reason = "error"
        return {
            "type": "final",
            "answer": answer,
            "steps": int(usage.get("step") or state.last_step or 0),
            "tokens": int(usage.get("tokens") or 0),
            "cost": float(usage.get("cost") or 0),
            "stopped_reason": reason,
        }

    async def task_stream(state: TaskState):
        try:
            try:
                await start_worker(state)
            except Exception as exc:  # noqa: BLE001
                state.final = {
                    "type": "final",
                    "answer": f"Не удалось запустить воркер: {exc}",
                    "steps": 0,
                    "tokens": 0,
                    "cost": 0.0,
                    "stopped_reason": "error",
                }
                await remember(state)
                yield _format_sse(state.final)
                return

            async for event in events(state):
                if event.get("type") == "final":
                    try:
                        await remember(state)
                    except Exception as exc:  # noqa: BLE001
                        event["history_error"] = str(exc)
                    async with app.state.active_lock:
                        if app.state.active is state:
                            app.state.active = None
                yield _format_sse(event)

            if state.final is None:
                state.final = cancelled_event(state)
                with suppress(Exception):
                    await remember(state)
                yield _format_sse(state.final)
        except asyncio.CancelledError:
            state.stopped = True
            raise
        finally:
            await finish(state)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host", "").lower() != app.state.host:
            return JSONResponse({"error": "Неверный Host."}, status_code=403)

        if request.url.path.startswith("/api/"):
            if request.method == "OPTIONS":
                return JSONResponse({"error": "CORS закрыт."}, status_code=403)
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer ") or not secrets.compare_digest(
                auth[7:], app.state.token
            ):
                return JSONResponse({"error": "Нет доступа."}, status_code=401)
            origin = request.headers.get("origin")
            if origin is not None and origin != app.state.origin:
                return JSONResponse({"error": "Чужой Origin."}, status_code=403)
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                if origin != app.state.origin:
                    return JSONResponse({"error": "Чужой Origin."}, status_code=403)

        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    async def health():
        return {"ok": True, "version": "0.1"}

    @app.get("/api/summary")
    async def summary():
        tasks = _load_history()
        limit = _budget_limit()
        spent = _spent_rub(tasks)
        return {
            "budget_limit": round(limit, 2),
            "spent": round(spent, 2),
            "remaining_rub": round(max(0.0, limit - spent), 2),
            "max_steps": int(os.environ.get("MAX_STEPS", "8")),
            "history": tasks[:30],
        }

    @app.get("/api/history")
    async def history():
        return {"tasks": _load_history()[:50]}

    @app.post("/api/task")
    async def start_task(payload: TaskIn):
        task = (payload.task or "").strip()
        if not task:
            return JSONResponse({"error": "Пустая задача."}, status_code=400)
        if len(task) > 4000:
            return JSONResponse(
                {"error": "Задача слишком длинная (максимум 4000 символов)."},
                status_code=400,
            )
        async with app.state.active_lock:
            if app.state.active is not None:
                return JSONResponse(
                    {"error": "Уже выполняется другая задача."}, status_code=409
                )
            state = TaskState(task=task)
            app.state.active = state
        return StreamingResponse(
            task_stream(state),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/stop")
    async def stop():
        state = app.state.active
        if state is None or state.proc is None:
            return {"ok": False, "note": "Нет активной задачи."}
        state.stopped = True
        state.pending_id = None
        await _terminate(state.proc)
        return {"ok": True}

    @app.post("/api/confirm")
    async def confirm(payload: ConfirmIn):
        state = app.state.active
        if state is None or state.proc is None:
            return JSONResponse({"error": "Нет активной задачи."}, status_code=409)
        if state.pending_id is None or state.pending_id != payload.id:
            return JSONResponse(
                {"error": "Запрос подтверждения устарел."}, status_code=409
            )
        if payload.action not in ("approve", "reject", "edit"):
            return JSONResponse({"error": "Неизвестное действие."}, status_code=400)
        text = (payload.text or "")[:5000]
        with suppress(Exception):
            await _write_command(
                state.proc,
                {
                    "type": "confirm_answer",
                    "id": payload.id,
                    "action": payload.action,
                    "text": text,
                },
            )
        state.pending_id = None
        return {"ok": True}

    @app.post("/api/shutdown")
    async def shutdown():
        state = app.state.active
        if state is not None:
            state.stopped = True
            await _terminate(state.proc)
        server = getattr(app.state, "uvicorn_server", None)
        if server is not None:
            server.should_exit = True

            async def force_exit() -> None:
                await asyncio.sleep(1.5)
                server.force_exit = True

            asyncio.create_task(force_exit())
        return {"ok": True}

    app.mount("/", StaticFiles(directory=str(RENDERER_DIR), html=True), name="ui")
    return app


def _free_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock


def main() -> int:
    token = os.environ.get("JARVIS_TOKEN", "")
    if len(token) < 32:
        print(
            "JARVIS_TOKEN не задан или слишком короткий. "
            "Сервер запускает только приложение.",
            file=sys.stderr,
        )
        return 2

    sock = _free_socket()
    port = sock.getsockname()[1]
    app = create_app(
        token=token,
        port=port,
        test_worker=os.environ.get("JARVIS_TEST_WORKER") == "1",
    )
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server
    print(f"JARVIS_PORT={port}", flush=True)
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
