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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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
        self.trash_file = Path(tempfile.gettempdir()) / f"omega_trash_{os.getpid()}.json"
        if self.history_file.exists():
            self.history_file.unlink()
        if self.trash_file.exists():
            self.trash_file.unlink()
        env = {
            **os.environ,
            "OMEGA_TOKEN": TOKEN,
            "OMEGA_TEST_WORKER": "1",
            "OMEGA_HISTORY_FILE": str(self.history_file),
            "OMEGA_TRASH_FILE": str(self.trash_file),
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

    def stream(self, task: str, chat_id: str = ""):
        body = json.dumps({"task": task, "chat_id": chat_id}, ensure_ascii=False)
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
        if self.trash_file.exists():
            self.trash_file.unlink()


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

payloads = []
worker.request_confirmation = (
    lambda payload: payloads.append(payload) or {"action": "reject"}
)
assert worker.safety.ask_confirm("Записать файл?", title="Записать файл?") is False
assert payloads[-1]["kind"] == "generic", payloads[-1]
assert payloads[-1]["title"] == "Записать файл?", payloads[-1]
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


def test_computer_tools() -> None:
    import config
    import safety
    import tools
    from tools import computer

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "allowed"
        root.mkdir()
        (root / "notes.txt").write_text("Привет, Омега!", encoding="utf-8")
        (root / "secret.env").write_text("TOKEN=123", encoding="utf-8")
        (root / "key.txt").write_text(
            'API_KEY = "abcdefghijklmnop123456"', encoding="utf-8"
        )
        app = Path(temp) / "test.exe"
        app.write_bytes(b"MZ")
        outside = Path(temp) / "outside.txt"
        outside.write_text("нельзя", encoding="utf-8")

        old_data = config.DATA_DIR
        old_confirm = safety.ask_confirm
        old_start = computer._start
        started = []
        try:
            config.DATA_DIR = Path(temp)
            safety.ask_confirm = lambda question, title=None, details=None: True
            computer._start = lambda path: started.append(str(path))

            listing = tools.execute("list_files", {"path": str(root)})
            names = {item["name"] for item in listing.get("entries", [])}
            check("компьютер: список файлов", {"notes.txt", "secret.env"} <= names, str(names))
            read = tools.execute("read_file", {"path": str(root / "notes.txt")})
            check("компьютер: чтение файла", read.get("text") == "Привет, Омега!", str(read))
            outside_read = tools.execute("read_file", {"path": str(outside)})
            traversal = tools.execute(
                "read_file", {"path": str(root / ".." / "outside.txt")}
            )
            check(
                "компьютер: любой путь вне папки разрешён",
                outside_read.get("text") == "нельзя"
                and traversal.get("text") == "нельзя",
                f"outside={outside_read}, traversal={traversal}",
            )
            secret = tools.execute("read_file", {"path": str(root / "secret.env")})
            secret_text = tools.execute("read_file", {"path": str(root / "key.txt")})
            check(
                "компьютер: секреты не читаются",
                "error" in secret and "error" in secret_text,
                f"name={secret}, text={secret_text}",
            )

            safety.ask_confirm = lambda question, title=None, details=None: False
            cancelled = tools.execute(
                "write_file",
                {"path": str(root / "new.txt"), "text": "текст"},
            )
            check(
                "компьютер: запись без подтверждения отменена",
                cancelled.get("cancelled") is True
                and not (root / "new.txt").exists(),
                str(cancelled),
            )

            safety.ask_confirm = lambda question, title=None, details=None: True
            written = tools.execute(
                "write_file",
                {"path": str(root / "new.txt"), "text": "строка"},
            )
            check(
                "компьютер: запись после подтверждения",
                written.get("written") == 6
                and (root / "new.txt").read_text(encoding="utf-8") == "строка",
                str(written),
            )
            appended = tools.execute(
                "write_file",
                {"path": str(root / "new.txt"), "text": "!", "mode": "append"},
            )
            check(
                "компьютер: дописывание файла",
                appended.get("mode") == "append"
                and (root / "new.txt").read_text(encoding="utf-8") == "строка!",
                str(appended),
            )
            folder = tools.execute("create_folder", {"path": str(root / "новая")})
            check(
                "компьютер: создание папки",
                folder.get("created") is True and (root / "новая").is_dir(),
                str(folder),
            )
            opened = tools.execute("open_path", {"path": str(root)})
            file_open = tools.execute("open_path", {"path": str(root / "notes.txt")})
            launched = tools.execute("launch_app", {"path": str(app)})
            blocked_app = tools.execute("launch_app", {"path": str(outside)})
            check(
                "компьютер: открытие папки и запуск любого exe",
                opened.get("opened") is True
                and "error" in file_open
                and launched.get("launched") is True
                and "error" in blocked_app
                and str(root) in started
                and str(app) in started,
                f"opened={opened}, file={file_open}, launched={launched}, blocked={blocked_app}",
            )
        finally:
            config.DATA_DIR = old_data
            safety.ask_confirm = old_confirm
            computer._start = old_start


def test_settings_js() -> None:
    """Настройки окна: миграция старых списков и новые ключи запуска."""
    script = """
const fs = require("fs");
const path = require("path");
const settings = require(process.argv[2]);
const root = process.argv[3];

const parsed = {
  hotkey: "CommandOrControl+Space",
  allowed_folders: ["C:/old"],
  allowed_apps: ["C:/old.exe"],
};
const legacy = settings.migrateLegacyAllowlists(root, parsed);
const saved = JSON.parse(
  fs.readFileSync(path.join(root, "data", "legacy_allowed.json"), "utf8"),
);
const clean = settings.sanitizeSettings(parsed);
const apps = settings.sanitizeSettings({
  allowed_apps: ["C:/a.exe", "C:/a.exe", 5, " "],
  launch_without_confirm: true,
});
const problems = [];
if (!legacy || legacy.allowed_folders[0] !== "C:/old") problems.push("legacy");
if (saved.allowed_apps[0] !== "C:/old.exe") problems.push("saved");
if ("allowed_folders" in parsed) problems.push("clean");
if (clean.allowed_apps.length !== 0) problems.push("clean-apps");
if (apps.allowed_apps.length !== 1) problems.push("apps");
if (apps.launch_without_confirm !== true) problems.push("toggle");
console.log(problems.length ? problems.join(",") : "OK");
"""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "data").mkdir(parents=True, exist_ok=True)
        script_file = root / "check.js"
        script_file.write_text(script, encoding="utf-8")
        try:
            completed = subprocess.run(
                ["node", str(script_file), str(ROOT / "desktop" / "settings.js"), str(root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except FileNotFoundError:
            check("настройки: миграция allowlist и запуск приложений", True, "пропущено: нет node")
            return
        check(
            "настройки: миграция allowlist и запуск приложений",
            completed.returncode == 0 and "OK" in (completed.stdout or ""),
            (completed.stdout or completed.stderr or "").strip()[-200:],
        )


def main() -> int:
    print("Тесты сервера (голос — при наличии модели)\n")
    ok, detail = test_worker_dialog()
    check("диалог send_message: правка и отказ", ok, "" if ok else detail)
    test_computer_tools()
    test_settings_js()
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

        shots_dir = ROOT / "data" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        shot_name = "shot-20260101-000000.png"
        shot_file = shots_dir / shot_name
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        try:
            status, headers, body = server.request(
                "GET", f"/api/screenshot?name={shot_name}", token=TOKEN
            )
            check(
                "снимок экрана отдаётся",
                status == 200
                and body.startswith(b"\x89PNG")
                and "image/png" in header_value(headers, "Content-Type"),
                f"status={status}, type={header_value(headers, 'Content-Type')}",
            )
            status, _, _ = server.request(
                "GET", "/api/screenshot?name=../config.py", token=TOKEN
            )
            check("снимок по чужому пути — 404", status == 404, str(status))
            status, _, _ = server.request(
                "GET", "/api/screenshot?name=secret.png", token=TOKEN
            )
            check("снимок с неверным именем — 404", status == 404, str(status))
            status, _, _ = server.request("GET", f"/api/screenshot?name={shot_name}")
            check("снимок без токена — 401", status == 401, str(status))
        finally:
            if shot_file.exists():
                shot_file.unlink()

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
        first_chat_id = (final or {}).get("chat_id") or ""

        conn, response = server.stream("вторая задача", chat_id=first_chat_id)
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
        check(
            "обе задачи в одном чате",
            len(summary.get("chats", [])) == 1,
            str(summary.get("chats")),
        )

        status, _, body = server.request("GET", "/api/chats", token=TOKEN)
        chats = json.loads(body.decode("utf-8")).get("chats", [])
        check(
            "чат хранит сообщения",
            status == 200
            and len(chats) == 1
            and len(chats[0].get("messages", [])) == 4,
            f"status={status}, chats={chats}",
        )
        message_id = (chats[0].get("messages") or [{}])[-1].get("id")
        status, _, _ = server.request(
            "DELETE",
            f"/api/chats/{chats[0]['id']}/messages/{message_id}",
            token=TOKEN,
            origin=server.origin,
        )
        status2, _, body = server.request("GET", "/api/summary", token=TOKEN)
        after_delete = json.loads(body.decode("utf-8")) if status2 == 200 else {}
        check(
            "удаление задачи",
            status == 200 and len(after_delete.get("history", [])) == 1,
            f"status={status}, history={len(after_delete.get('history', []))}",
        )

        status, _, body = server.request(
            "POST",
            f"/api/chats/{chats[0]['id']}/messages/{message_id}/restore",
            token=TOKEN,
            origin=server.origin,
            body={},
        )
        status2, _, body = server.request("GET", "/api/chats", token=TOKEN)
        restored = json.loads(body.decode("utf-8")).get("chats", []) if status2 == 200 else []
        check(
            "удалённый ответ возвращается из корзины",
            status == 200
            and len(restored) == 1
            and len(restored[0].get("messages", [])) == 4,
            f"status={status}, chats={restored}",
        )

        status, _, _ = server.request(
            "DELETE",
            f"/api/chats/{chats[0]['id']}",
            token=TOKEN,
            origin=server.origin,
        )
        status2, _, body = server.request("GET", "/api/chats", token=TOKEN)
        remaining = json.loads(body.decode("utf-8")).get("chats", []) if status2 == 200 else []
        check(
            "удаление чата",
            status == 200 and remaining == [],
            f"status={status}, chats={remaining}",
        )
    finally:
        server.close()

    ok = sum(1 for _, passed, _ in results if passed)
    failed = len(results) - ok
    print(f"\nИтого: ок {ok}, ошибок {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
