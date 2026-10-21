# Тесты локального сервера без вызовов модели: режим --selftest.
# Проверяем токен, Origin, Host, CSP, SSE, подтверждение, стоп и историю.

import http.client
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "desktop" / "server" / "app.py"
VOICE_FIXTURE = ROOT / "desktop" / "tests" / "fixtures" / "voice_ru.wav"
MODEL_DIR = Path(os.environ.get("OMEGA_MODEL_DIR") or (ROOT / "data" / "models"))
TOKEN = "test-" + "a" * 60
HOST = "127.0.0.1"

results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, bool(condition), detail))
    mark = "ОК      " if condition else "ОШИБКА  "
    print(f"  {mark} {name}" + (f" ({detail})" if detail else ""))


class Server:
    def __init__(self) -> None:
        self.history_file = Path(tempfile.gettempdir()) / f"omega_history_{os.getpid()}.json"
        if self.history_file.exists():
            self.history_file.unlink()
        env = {
            **os.environ,
            "OMEGA_TOKEN": TOKEN,
            "OMEGA_TEST_WORKER": "1",
            "OMEGA_HISTORY_FILE": str(self.history_file),
            "BUDGET_LIMIT_RUB": "500",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        self.proc = subprocess.Popen(
            [sys.executable, str(APP)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.lines: "queue.Queue[tuple[str, str]]" = queue.Queue()
        for stream, name in ((self.proc.stdout, "out"), (self.proc.stderr, "err")):
            threading.Thread(
                target=self._reader, args=(stream, name), daemon=True
            ).start()
        self.port = self._wait_port()

    def _reader(self, stream, name: str) -> None:
        for line in stream:
            self.lines.put((name, line.rstrip()))

    def _wait_port(self) -> int:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                name, line = self.lines.get(timeout=0.5)
            except queue.Empty:
                if self.proc.poll() is not None:
                    break
                continue
            if name == "out" and line.startswith("OMEGA_PORT="):
                port = int(line.split("=", 1)[1])
                self.port = port
                self.wait_ready(port)
                return port
            if name == "err" and line:
                print(f"    [server] {line}")
        raise RuntimeError("Сервер не сообщил порт.")

    def wait_ready(self, port: int) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                status, _, _ = self.request("GET", "/api/health", token=TOKEN)
                if status == 200:
                    return
            except OSError:
                pass
            time.sleep(0.15)
        raise RuntimeError("Сервер не прошёл проверку здоровья.")

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        origin: str | None = None,
        body: dict | None = None,
        raw: bytes | None = None,
        content_type: str | None = None,
        extra_headers: dict | None = None,
        timeout: int = 60,
    ):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if origin is not None:
            headers["Origin"] = origin
        payload = None
        if raw is not None:
            payload = raw
            if content_type:
                headers["Content-Type"] = content_type
        elif body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        conn = http.client.HTTPConnection(HOST, self.port, timeout=timeout)
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def stream(self, task: str):
        body = json.dumps({"task": task}, ensure_ascii=False)
        conn = http.client.HTTPConnection(HOST, self.port, timeout=30)
        conn.request(
            "POST",
            "/api/task",
            body=body.encode("utf-8"),
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Origin": self.origin,
                "Content-Type": "application/json",
            },
        )
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError(f"Плохой статус потока: {response.status}")
        return conn, response

    @property
    def origin(self) -> str:
        return f"http://{HOST}:{self.port}"

    def close(self) -> None:
        try:
            self.request("POST", "/api/shutdown", token=TOKEN, origin=self.origin)
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
        if self.history_file.exists():
            self.history_file.unlink()


def read_events(response):
    data_lines = []
    while True:
        raw = response.readline()
        if not raw:
            return
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line == "":
            if data_lines:
                try:
                    event = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    event = None
                data_lines = []
                if event:
                    yield event
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())


def header_value(headers: dict, name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def whisper_model_ready() -> bool:
    return any(MODEL_DIR.rglob("model.bin"))


def test_worker_dialog() -> tuple[bool, str]:
    """Проверяет диалог send_message в отдельном процессе, без модели."""
    code = r"""
import sys
from pathlib import Path
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "desktop" / "server"))
import config
config.DATA_DIR = Path(sys.argv[1])
config.DATA_DIR.mkdir(parents=True, exist_ok=True)
import worker
from tools import messages

draft = messages.draft_message(
    recipient="Тест",
    company="ООО Тест",
    contact="@test",
    text="Здравствуйте! Это тестовый черновик сообщения длиной больше двадцати символов.",
)
assert "draft_id" in draft, draft
worker.request_confirmation = lambda payload: {
    "action": "edit",
    "text": "Здравствуйте! Это изменённый текст черновика, тоже достаточно длинный.",
}
result = worker.ui_send_message(draft["draft_id"])
assert result.get("status") == "would_send", result
data = messages._load()
item = next(m for m in data["messages"] if m["id"] == draft["draft_id"])
assert item["text"].startswith("Здравствуйте! Это изменённый"), item["text"]
assert item["confirmed_by_user"] is True
assert item["status"] == "would_send"

second = messages.draft_message(
    recipient="Второй",
    text="Здравствуйте! Второй тестовый черновик достаточной длины для проверки.",
)
worker.request_confirmation = lambda payload: {"action": "reject"}
result2 = worker.ui_send_message(second["draft_id"])
assert result2.get("status") == "cancelled", result2
sys.stderr.write("диалог воркера: ок\n")
"""
    with tempfile.TemporaryDirectory() as temp:
        completed = subprocess.run(
            [sys.executable, "-c", code, temp],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    return completed.returncode == 0, (completed.stderr or "").strip()[-300:]


def main() -> int:
    print("Тесты сервера (голос — при наличии модели)\n")
    ok, detail = test_worker_dialog()
    check("диалог send_message: правка и отказ", ok, "" if ok else detail)
    server = Server()
    try:
        status, _, _ = server.request("GET", "/api/health")
        check("без токена — 401", status == 401, str(status))

        status, _, _ = server.request("GET", "/api/health", token="wrong")
        check("чужой токен — 401", status == 401, str(status))

        status, _, body = server.request("GET", "/api/health", token=TOKEN)
        check("свой токен — 200", status == 200 and b'"ok"' in body, str(status))

        status, headers, body = server.request("GET", "/index.html")
        check("статика открывается", status == 200 and b"<!DOCTYPE html>" in body)
        csp = header_value(headers, "Content-Security-Policy")
        check(
            "CSP запрещает фреймы и внешние скрипты",
            "frame-ancestors 'none'" in csp and "script-src 'self'" in csp,
            csp[:40] or "заголовка нет",
        )

        status, _, _ = server.request(
            "POST",
            "/api/transcribe",
            token=TOKEN,
            origin=server.origin,
            raw=b"x" * 128,
        )
        check("распознавание без аудио-типа — 415", status == 415, str(status))

        status, _, _ = server.request(
            "POST",
            "/api/transcribe",
            token=TOKEN,
            origin=server.origin,
            raw=b"",
            content_type="audio/wav",
        )
        check("пустая запись — 400", status == 400, str(status))

        status, _, _ = server.request(
            "POST",
            "/api/transcribe",
            token=TOKEN,
            origin=server.origin,
            raw=b"not audio" * 40,
            content_type="audio/wav",
        )
        check("битое аудио — 400", status == 400, str(status))

        status, _, _ = server.request(
            "POST",
            "/api/transcribe?language=de",
            token=TOKEN,
            origin=server.origin,
            raw=b"x" * 128,
            content_type="audio/wav",
        )
        check("неизвестный язык — 400", status == 400, str(status))

        if VOICE_FIXTURE.exists() and whisper_model_ready():
            audio = VOICE_FIXTURE.read_bytes()
            status, _, body = server.request(
                "POST",
                "/api/transcribe?language=ru",
                token=TOKEN,
                origin=server.origin,
                raw=audio,
                content_type="audio/wav",
                timeout=180,
            )
            try:
                voice = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                voice = {}
            check(
                "реальная русская запись распознана",
                status == 200
                and "привет" in str(voice.get("text", "")).lower()
                and "проверка" in str(voice.get("text", "")).lower(),
                str(voice.get("text", status)),
            )
        else:
            check(
                "реальная русская запись распознана",
                True,
                "пропущено: нет модели или тестового WAV",
            )

        status, _, _ = server.request("GET", "/../config.py")
        check("выход за папку закрыт", status in (400, 403, 404), str(status))

        status, _, _ = server.request("POST", "/api/task", token=TOKEN, body={"task": "x"})
        check("POST без Origin — 403", status == 403, str(status))

        status, _, _ = server.request(
            "POST",
            "/api/task",
            token=TOKEN,
            origin="https://evil.example",
            body={"task": "x"},
        )
        check("чужой Origin — 403", status == 403, str(status))

        status, _, _ = server.request(
            "POST", "/api/task", token=TOKEN, origin=server.origin, body={"task": "  "}
        )
        check("пустая задача — 400", status == 400, str(status))

        status, _, _ = server.request(
            "OPTIONS",
            "/api/task",
            token=TOKEN,
            origin="https://evil.example",
        )
        check("CORS preflight — 403", status == 403, str(status))

        status, _, _ = server.request(
            "GET",
            "/api/health",
            token=TOKEN,
            extra_headers={"Host": "evil.example"},
        )
        check("чужой Host — 403", status == 403, str(status))

        conn, response = server.stream("тестовая задача")
        confirm = None
        for event in read_events(response):
            if event.get("type") == "confirm":
                confirm = event
                break
        check("диалог подтверждения пришёл", confirm is not None)
        if confirm:
            check(
                "в диалоге есть компания и канал",
                confirm.get("company") == "ООО Тест"
                and confirm.get("channel") == "telegram",
            )
            status, _, _ = server.request(
                "POST",
                "/api/confirm",
                token=TOKEN,
                origin=server.origin,
                body={"id": confirm["id"], "action": "approve"},
            )
            check("подтверждение принято", status == 200, str(status))
        final = None
        for event in read_events(response):
            if event.get("type") == "final":
                final = event
                break
        conn.close()
        check(
            "итог после подтверждения",
            final is not None and final.get("stopped_reason") == "done",
            (final or {}).get("stopped_reason", "нет"),
        )
        check(
            "остаток бюджета посчитан",
            final is not None and isinstance(final.get("remaining_rub"), (int, float)),
        )

        conn, response = server.stream("вторая задача")
        first = None
        for event in read_events(response):
            if event.get("type") in ("step", "tool"):
                first = event
                break
        check("второй поток стартовал", first is not None)
        status, _, _ = server.request(
            "POST", "/api/stop", token=TOKEN, origin=server.origin
        )
        check("стоп принят", status == 200, str(status))
        final = None
        for event in read_events(response):
            if event.get("type") == "final":
                final = event
                break
        conn.close()
        check(
            "стоп даёт статус cancelled",
            final is not None and final.get("stopped_reason") == "cancelled",
            (final or {}).get("stopped_reason", "нет"),
        )

        status, _, body = server.request("GET", "/api/summary", token=TOKEN)
        summary = json.loads(body.decode("utf-8"))
        check(
            "в истории две задачи",
            len(summary.get("history", [])) == 2,
            str(len(summary.get("history", []))),
        )
        check(
            "бюджет уменьшился",
            0 < summary.get("spent", 0) < 500
            and summary.get("remaining_rub", 0) < 500,
            f"spent={summary.get('spent')}",
        )
    finally:
        server.close()

    ok = sum(1 for _, passed, _ in results if passed)
    failed = len(results) - ok
    print(f"\nИтого: ок {ok}, ошибок {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
