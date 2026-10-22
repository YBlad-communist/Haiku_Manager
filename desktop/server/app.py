# Локальный сервер приложения.
# Слушает только 127.0.0.1 на случайном порту, требует токен и проверяет Origin.
# Задачу выполняет отдельный процесс worker.py, поэтому «Стоп» убивает только его.

import asyncio
import io
import json
import os
import re
import secrets
import socket
import sys
import threading
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RENDERER_DIR = Path(__file__).resolve().parents[1] / "renderer"
WORKER_PATH = Path(__file__).with_name("worker.py")

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 60.0
VOICE_LANGUAGES = ("ru", "en", "auto")
SCREENSHOT_NAME_RE = re.compile(r"^shot-[0-9]{8}-[0-9]{6}\.png$")
_whisper_model = None
_whisper_lock = threading.Lock()


class AudioTooLong(Exception):
    pass


class EmptySpeech(Exception):
    pass


class SpeechUnavailable(Exception):
    pass

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


class TaskIn(BaseModel):
    task: str = ""
    chat_id: str = ""


class ConfirmIn(BaseModel):
    id: str = ""
    action: str = ""
    text: str = ""


@dataclass
class TaskState:
    task: str
    chat_id: str = ""
    user_message_id: str = ""
    history: list[dict] = field(default_factory=list)
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
    override = os.environ.get("OMEGA_HISTORY_FILE")
    return Path(override) if override else PROJECT_ROOT / "data" / "history.json"


def _settings_path() -> Path:
    return PROJECT_ROOT / "data" / "settings.json"


def _budget_limit() -> float:
    override = os.environ.get("BUDGET_LIMIT_RUB")
    if override is not None:
        try:
            return max(0.0, float(override))
        except ValueError:
            pass
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        value = float(data.get("budget_limit_rub", 500))
        return max(0.0, value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return 500.0


def _voice_language() -> str:
    override = os.environ.get("OMEGA_VOICE_LANGUAGE")
    if override in VOICE_LANGUAGES:
        return override
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        value = str(data.get("voice_language", "ru"))
        if value in VOICE_LANGUAGES:
            return value
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return "ru"


def _load_whisper_model():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # noqa: BLE001
            raise SpeechUnavailable(
                "Распознавание речи не установлено. Установи faster-whisper."
            ) from exc
        model_name = os.environ.get("OMEGA_WHISPER_MODEL", "small")
        model_root = Path(
            os.environ.get("OMEGA_MODEL_DIR") or (PROJECT_ROOT / "data" / "models")
        )
        try:
            model_root.mkdir(parents=True, exist_ok=True)
            _whisper_model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                download_root=str(model_root),
            )
        except Exception as exc:  # noqa: BLE001
            raise SpeechUnavailable(
                "Не удалось подготовить модель распознавания речи. "
                "Проверь интернет и свободное место."
            ) from exc
        return _whisper_model


def _decode_audio(data: bytes):
    try:
        import av
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        raise SpeechUnavailable(
            "Распознавание речи не установлено. Установи faster-whisper."
        ) from exc
    try:
        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=16000,
        )
        chunks: list[bytes] = []
        with av.open(io.BytesIO(data), mode="r") as container:
            if not container.streams.audio:
                raise ValueError("В записи нет звука.")
            for frame in container.decode(audio=0):
                for resampled in resampler.resample(frame):
                    chunks.append(resampled.to_ndarray().tobytes())
            for resampled in resampler.resample(None):
                chunks.append(resampled.to_ndarray().tobytes())
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Не удалось прочитать аудио.") from exc
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(b"".join(chunks), dtype=np.int16).astype(np.float32) / 32768.0


def _transcribe_audio(data: bytes, language: str) -> tuple[str, str, float]:
    audio = _decode_audio(data)
    if audio.size == 0:
        raise ValueError("В записи нет звука.")
    duration = float(audio.size) / 16000.0
    if duration > MAX_AUDIO_SECONDS + 0.5:
        raise AudioTooLong(
            f"Запись слишком длинная. Максимум {int(MAX_AUDIO_SECONDS)} секунд."
        )
    model = _load_whisper_model()
    segments, info = model.transcribe(
        audio,
        language=None if language == "auto" else language,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        without_timestamps=True,
    )
    text = " ".join(part.strip() for part in (seg.text for seg in segments) if part.strip())
    text = " ".join(text.split())
    if not text:
        raise EmptySpeech(
            "Речь не распознана. Попробуй ещё раз ближе к микрофону."
        )
    return text, str(info.language or language), duration


async def _read_limited_body(request: Request, limit: int) -> bytes | None:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _chat_title(text: str) -> str:
    title = " ".join(str(text or "").split())
    return title[:70] or "Новый чат"


def _new_chat(title: str = "Новый чат") -> dict:
    stamp = _now()
    return {
        "id": uuid.uuid4().hex[:12],
        "title": _chat_title(title),
        "created_at": stamp,
        "updated_at": stamp,
        "messages": [],
    }


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clean_message(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    role = item.get("role")
    if role not in ("user", "assistant"):
        return None
    message = {
        "id": str(item.get("id") or uuid.uuid4().hex[:12])[:32],
        "role": role,
        "text": str(item.get("text") or "")[:100_000],
        "created_at": str(item.get("created_at") or _now())[:40],
    }
    if role == "assistant":
        message["steps"] = _as_int(item.get("steps"))
        message["tokens"] = _as_int(item.get("tokens"))
        message["cost"] = round(_as_float(item.get("cost")), 4)
        message["stopped_reason"] = str(item.get("stopped_reason") or "")[:40]
        task_id = str(item.get("task_id") or "")[:32]
        if task_id:
            message["task_id"] = task_id
    return message


def _clean_chat(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    chat_id = str(item.get("id") or uuid.uuid4().hex[:12])[:32]
    messages = [
        message
        for message in (_clean_message(raw) for raw in item.get("messages") or [])
        if message is not None
    ]
    created = str(item.get("created_at") or _now())[:40]
    updated = str(item.get("updated_at") or created)[:40]
    return {
        "id": chat_id,
        "title": _chat_title(item.get("title")),
        "created_at": created,
        "updated_at": updated,
        "messages": messages,
    }


def _legacy_chat(tasks: list[dict]) -> dict:
    messages = []
    for index, item in enumerate(reversed(tasks)):
        created = str(item.get("created_at") or _now())[:40]
        task_id = str(item.get("id") or f"task{index}")[:28]
        messages.append(
            {
                "id": f"u-{task_id}"[:32],
                "role": "user",
                "text": str(item.get("task") or ""),
                "created_at": created,
            }
        )
        answer = {
            "id": f"a-{task_id}"[:32],
            "role": "assistant",
            "text": str(item.get("answer") or ""),
            "created_at": created,
            "steps": _as_int(item.get("steps")),
            "tokens": _as_int(item.get("tokens")),
            "cost": round(_as_float(item.get("cost")), 4),
            "stopped_reason": str(item.get("stopped_reason") or "")[:40],
        }
        if task_id:
            answer["task_id"] = task_id
        messages.append(answer)
    oldest = str(tasks[-1].get("created_at") or _now())[:40] if tasks else _now()
    newest = str(tasks[0].get("created_at") or _now())[:40] if tasks else oldest
    return {
        "id": "legacy",
        "title": "Старые задачи",
        "created_at": oldest,
        "updated_at": newest,
        "messages": messages,
    }


def _load_store() -> dict:
    path = _history_path()
    if not path.exists():
        return {"tasks": [], "chats": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"tasks": [], "chats": []}
    if not isinstance(data, dict):
        return {"tasks": [], "chats": []}
    tasks = [item for item in data.get("tasks") or [] if isinstance(item, dict)]
    chats = [
        chat
        for chat in (_clean_chat(raw) for raw in data.get("chats") or [])
        if chat is not None
    ]
    if "chats" not in data and tasks:
        chats = [_legacy_chat(tasks)]
    return {"tasks": tasks[:100], "chats": chats[:50]}


def _save_store(tasks: list[dict], chats: list[dict]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {"tasks": tasks[:100], "chats": chats[:50]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temp, path)


def _load_history() -> list[dict]:
    return _load_store()["tasks"]


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
    app.state.transcribe_lock = asyncio.Lock()

    async def remember(state: TaskState) -> dict:
        usage = state.last_usage or {}
        final = state.final or {}
        async with app.state.history_lock:
            store = _load_store()
            tasks = store["tasks"]
            chats = store["chats"]
            chat = next(
                (item for item in chats if item.get("id") == state.chat_id),
                None,
            )
            if chat is None:
                chat = _new_chat(state.task)
                chats.insert(0, chat)
                state.chat_id = chat["id"]
            cost = float(final.get("cost") or usage.get("cost") or 0)
            entry = {
                "id": uuid.uuid4().hex[:10],
                "created_at": _now(),
                "chat_id": chat["id"],
                "task": state.task,
                "answer": str(final.get("answer") or ""),
                "steps": int(final.get("steps") or usage.get("step") or 0),
                "tokens": int(final.get("tokens") or usage.get("tokens") or 0),
                "cost": round(cost, 4),
                "stopped_reason": str(final.get("stopped_reason") or "error"),
            }
            tasks.insert(0, entry)
            message_id = uuid.uuid4().hex[:12]
            chat["messages"].append(
                {
                    "id": message_id,
                    "role": "assistant",
                    "text": entry["answer"],
                    "created_at": entry["created_at"],
                    "steps": entry["steps"],
                    "tokens": entry["tokens"],
                    "cost": entry["cost"],
                    "stopped_reason": entry["stopped_reason"],
                    "task_id": entry["id"],
                }
            )
            chat["updated_at"] = entry["created_at"]
            if chat["title"] in ("", "Новый чат"):
                chat["title"] = _chat_title(state.task)
            chats.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
            _save_store(tasks, chats)
            limit = _budget_limit()
            remaining = max(0.0, limit - _spent_rub(tasks))
            entry["budget_limit"] = limit
            entry["remaining_rub"] = remaining
        state.remembered = True
        if state.final is not None:
            state.final["remaining_rub"] = remaining
            state.final["chat_id"] = chat["id"]
            state.final["message_id"] = message_id
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
            if key not in ("OMEGA_TOKEN", "OMEGA_TEST_WORKER")
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
        await _write_command(
            state.proc,
            {"type": "run", "task": state.task, "history": state.history},
        )

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
        return {"ok": True, "version": "0.4"}

    @app.get("/api/screenshot")
    async def screenshot(name: str = ""):
        """Отдаёт снимок экрана из data/screenshots."""
        if not SCREENSHOT_NAME_RE.match(name or ""):
            return JSONResponse({"error": "Нет такого снимка."}, status_code=404)
        folder = PROJECT_ROOT / "data" / "screenshots"
        target = folder / name
        try:
            resolved = target.resolve()
            if not resolved.is_file() or resolved.parent != folder.resolve():
                return JSONResponse({"error": "Нет такого снимка."}, status_code=404)
            payload = resolved.read_bytes()
        except OSError:
            return JSONResponse({"error": "Нет такого снимка."}, status_code=404)
        return Response(
            content=payload,
            media_type="image/png",
            headers={"Content-Disposition": "inline"},
        )

    @app.post("/api/transcribe")
    async def transcribe(request: Request):
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("audio/"):
            return JSONResponse(
                {"error": "Нужен аудиофайл."},
                status_code=415,
            )
        length_header = request.headers.get("content-length")
        if length_header:
            try:
                if int(length_header) > MAX_AUDIO_BYTES:
                    return JSONResponse(
                        {"error": "Запись слишком большая."},
                        status_code=413,
                    )
            except ValueError:
                pass
        data = await _read_limited_body(request, MAX_AUDIO_BYTES)
        if data is None:
            return JSONResponse(
                {"error": "Запись слишком большая."},
                status_code=413,
            )
        if len(data) < 128:
            return JSONResponse(
                {"error": "Пустая запись."},
                status_code=400,
            )
        language = request.query_params.get("language") or _voice_language()
        if language not in VOICE_LANGUAGES:
            return JSONResponse(
                {"error": "Неизвестный язык распознавания."},
                status_code=400,
            )
        if app.state.transcribe_lock.locked():
            return JSONResponse(
                {"error": "Уже распознаю другую запись."},
                status_code=409,
            )
        async with app.state.transcribe_lock:
            try:
                text, detected, duration = await asyncio.to_thread(
                    _transcribe_audio, data, language
                )
            except AudioTooLong as exc:
                return JSONResponse({"error": str(exc)}, status_code=413)
            except EmptySpeech as exc:
                return JSONResponse({"error": str(exc)}, status_code=422)
            except SpeechUnavailable as exc:
                return JSONResponse({"error": str(exc)}, status_code=503)
            except ValueError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                print(f"Ошибка распознавания: {exc}", file=sys.stderr)
                return JSONResponse(
                    {"error": "Не удалось распознать речь."},
                    status_code=500,
                )
        return {
            "text": text,
            "language": detected,
            "duration": round(duration, 2),
            "model": os.environ.get("OMEGA_WHISPER_MODEL", "small"),
        }

    @app.get("/api/summary")
    async def summary():
        store = _load_store()
        tasks = store["tasks"]
        limit = _budget_limit()
        spent = _spent_rub(tasks)
        chats = [
            {
                "id": chat["id"],
                "title": chat["title"],
                "created_at": chat["created_at"],
                "updated_at": chat["updated_at"],
                "message_count": len(chat["messages"]),
            }
            for chat in store["chats"]
        ]
        return {
            "budget_limit": round(limit, 2),
            "spent": round(spent, 2),
            "remaining_rub": round(max(0.0, limit - spent), 2),
            "max_steps": int(os.environ.get("MAX_STEPS", "8")),
            "history": tasks[:30],
            "chats": chats,
        }

    @app.get("/api/history")
    async def history():
        return {"tasks": _load_history()[:50]}

    @app.get("/api/chats")
    async def chats_list():
        return {"chats": _load_store()["chats"]}

    @app.delete("/api/chats/{chat_id}")
    async def delete_chat(chat_id: str):
        async with app.state.history_lock:
            store = _load_store()
            removed_chat = next(
                (chat for chat in store["chats"] if chat.get("id") == chat_id),
                None,
            )
            if removed_chat is None:
                return JSONResponse({"error": "Чат не найден."}, status_code=404)
            store["chats"] = [
                chat for chat in store["chats"] if chat.get("id") != chat_id
            ]
            task_ids = {
                message.get("task_id")
                for message in removed_chat.get("messages") or []
                if message.get("task_id")
            }
            store["tasks"] = [
                task
                for task in store["tasks"]
                if task.get("chat_id") != chat_id and task.get("id") not in task_ids
            ]
            _save_store(store["tasks"], store["chats"])
        return {"ok": True}

    @app.delete("/api/chats/{chat_id}/messages/{message_id}")
    async def delete_message(chat_id: str, message_id: str):
        async with app.state.history_lock:
            store = _load_store()
            chat = next(
                (item for item in store["chats"] if item.get("id") == chat_id),
                None,
            )
            if chat is None:
                return JSONResponse({"error": "Чат не найден."}, status_code=404)
            removed = next(
                (item for item in chat["messages"] if item.get("id") == message_id),
                None,
            )
            if removed is None:
                return JSONResponse({"error": "Сообщение не найдено."}, status_code=404)
            chat["messages"] = [
                item for item in chat["messages"] if item.get("id") != message_id
            ]
            task_id = removed.get("task_id")
            if task_id:
                store["tasks"] = [
                    task for task in store["tasks"] if task.get("id") != task_id
                ]
            chat["updated_at"] = _now()
            _save_store(store["tasks"], store["chats"])
        return {"ok": True, "chat": chat}

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
                    {"error": "Дождись, пока Омега закончит задачу."}, status_code=409
                )
            async with app.state.history_lock:
                store = _load_store()
                chat = next(
                    (
                        item
                        for item in store["chats"]
                        if item.get("id") == payload.chat_id
                    ),
                    None,
                )
                if chat is None:
                    chat = _new_chat(task)
                    store["chats"].insert(0, chat)
                stamp = _now()
                message_id = uuid.uuid4().hex[:12]
                chat["messages"].append(
                    {
                        "id": message_id,
                        "role": "user",
                        "text": task,
                        "created_at": stamp,
                    }
                )
                chat["updated_at"] = stamp
                if chat["title"] in ("", "Новый чат"):
                    chat["title"] = _chat_title(task)
                store["chats"].sort(
                    key=lambda item: str(item.get("updated_at") or ""),
                    reverse=True,
                )
                history = [
                    {
                        "role": message["role"],
                        "content": str(message.get("text") or "")[:4000],
                    }
                    for message in chat["messages"][:-1][-10:]
                    if message.get("role") in ("user", "assistant")
                    and message.get("text")
                ]
                _save_store(store["tasks"], store["chats"])
            state = TaskState(
                task=task,
                chat_id=chat["id"],
                user_message_id=message_id,
                history=history,
            )
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
        if payload.action not in ("approve", "reject", "edit", "always"):
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
    token = os.environ.get("OMEGA_TOKEN", "")
    if len(token) < 32:
        print(
            "OMEGA_TOKEN не задан или слишком короткий. "
            "Сервер запускает только приложение.",
            file=sys.stderr,
        )
        return 2

    sock = _free_socket()
    port = sock.getsockname()[1]
    app = create_app(
        token=token,
        port=port,
        test_worker=os.environ.get("OMEGA_TEST_WORKER") == "1",
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
    print(f"OMEGA_PORT={port}", flush=True)
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
