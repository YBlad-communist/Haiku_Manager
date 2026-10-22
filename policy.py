# Политика Омеги: границы доступа, правила подтверждения, корзина.
# Здесь собрано всё, что должно происходить одинаково в консоли и в окне приложения.

import base64
import os
import re
import subprocess
from pathlib import Path

import config
import safety


# --- Действия, которые всегда требуют подтверждения пользователя ---
CONFIRM_ACTIONS = (
    "write_file",
    "create_folder",
    "delete_files",
    "download_file",
    "screenshot",
    "launch_app",
)

# Действия, которые выполняются без вопроса.
FREE_ACTIONS = (
    "list_files",
    "read_file",
    "open_path",
    "search_web",
    "fetch_page",
    "save_to_table",
)

# Программы, которые умеют выполнять команды. Омега их не запускает.
SHELL_BLOCKLIST = frozenset(
    {
        "cmd.exe",
        "command.com",
        "powershell.exe",
        "pwsh.exe",
        "bash.exe",
        "sh.exe",
        "wsl.exe",
        "mshta.exe",
        "rundll32.exe",
        "regsvr32.exe",
        "cscript.exe",
        "wscript.exe",
        "msiexec.exe",
        "certutil.exe",
        "bitsadmin.exe",
        "installutil.exe",
        "forfiles.exe",
        "schtasks.exe",
    }
)


def _norm(path) -> str:
    """Нормализованный путь для сравнения: регистр и разделители не важны."""
    return os.path.normcase(os.path.abspath(str(path)))


def _real(path) -> Path:
    """Настоящий путь: разрывает симлинки и убирает «..»."""
    return Path(os.path.realpath(os.path.abspath(os.path.expanduser(str(path)))))


def is_inside(child, parent) -> bool:
    """Внутри ли child папки parent."""
    try:
        child_norm = _norm(child)
        parent_norm = _norm(parent).rstrip("\\/")
    except (OSError, ValueError):
        return False
    if child_norm == parent_norm:
        return True
    return child_norm.startswith(parent_norm + os.sep)


def _known_drives() -> list[Path]:
    drives: list[Path] = []
    letters = {os.environ.get("SystemDrive", "C:")[:1].upper(), "C", "D", "E"}
    for letter in letters:
        root = Path(f"{letter}:\\")
        if root.exists():
            drives.append(root)
    return drives


def forbidden_zones() -> list[Path]:
    """Папки, куда Омега не ходит: системные и с секретами."""
    zones: list[Path] = []

    def add(value) -> None:
        if not value:
            return
        try:
            resolved = _real(value)
        except (OSError, ValueError):
            return
        if resolved not in zones:
            zones.append(resolved)

    for name in (
        "SystemRoot",
        "windir",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramData",
    ):
        add(os.environ.get(name))

    home = Path(os.path.expanduser("~"))
    for name in (".ssh", ".aws", ".azure", ".gnupg"):
        add(home / name)
    add(home / ".config" / "gcloud")
    add(home / "AppData" / "Roaming" / "Microsoft" / "Credentials")

    for drive in _known_drives():
        add(drive / "$Recycle.Bin")
        add(drive / "System Volume Information")
        add(drive / "Recovery")

    return zones


def is_forbidden(path) -> bool:
    """Находится ли путь в запрещённой зоне."""
    try:
        target = _real(path)
    except (OSError, ValueError):
        return True
    return any(is_inside(target, zone) for zone in forbidden_zones())


def protected_paths() -> list[Path]:
    """Файлы, которые Омега не удаляет даже с подтверждением."""
    return [
        config.PROJECT_DIR / ".env",
        config.SETTINGS_FILE,
        config.DATA_DIR / "history.json",
        config.DATA_DIR / "outbox.json",
        config.DATA_DIR / "optouts.txt",
    ]


def is_protected(path) -> bool:
    """Является ли путь служебным файлом Омеги."""
    try:
        target = _norm(_real(path))
    except (OSError, ValueError):
        return True
    return any(target == _norm(item) for item in protected_paths())


def _as_text(value) -> str:
    """Путь как строка: принимает и str, и Path."""
    if isinstance(value, str):
        return value
    try:
        return os.fspath(value)
    except TypeError:
        return ""


def resolve_path(value) -> tuple[Path | None, str | None]:
    """Превращает строку в настоящий абсолютный путь."""
    raw = _as_text(value).strip().strip('"')
    if not raw:
        return None, "Нужен путь строкой."
    if not os.path.isabs(os.path.expanduser(raw)):
        return None, "Нужен абсолютный путь."
    try:
        return _real(raw), None
    except (OSError, ValueError):
        return None, "Не удалось разобрать путь."


def resolve_raw(value) -> tuple[Path | None, str | None]:
    """Абсолютный путь, но без разрыва симлинков: им видно сам ссылку."""
    raw = _as_text(value).strip().strip('"')
    if not raw:
        return None, "Нужен путь строкой."
    expanded = os.path.expanduser(raw)
    if not os.path.isabs(expanded):
        return None, "Нужен абсолютный путь."
    try:
        return Path(os.path.abspath(expanded)), None
    except (OSError, ValueError):
        return None, "Не удалось разобрать путь."


# --- Подтверждение пользователя ---

_CONFIRM_HOOK = None


def set_confirm_hook(hook) -> None:
    """Окно приложения подменяет консольный вопрос своим диалогом."""
    global _CONFIRM_HOOK
    _CONFIRM_HOOK = hook


def confirm(
    kind: str,
    title: str,
    question: str,
    details: str = "",
    always_path: str = "",
) -> dict:
    """Спрашивает подтверждение и возвращает решение пользователя.

    kind — что именно подтверждаем, always_path — путь, который можно
    разрешить навсегда (только для запуска приложений).
    """
    text = question if not details else f"{question}\n\n{details}"
    payload = {
        "kind": kind,
        "title": title,
        "text": text,
        "always_path": always_path,
    }
    hook = _CONFIRM_HOOK
    if hook is not None:
        answer = hook(payload) or {}
        action = str(answer.get("action", ""))
        return {
            "approved": action in ("approve", "edit", "always"),
            "always": action == "always" or bool(answer.get("always")),
            "answer": answer,
        }
    approved = safety.ask_confirm(text, title=title)
    return {"approved": bool(approved), "always": False, "answer": {}}


def needs_confirmation(kind: str) -> bool:
    """Требует ли действие подтверждения."""
    return kind in CONFIRM_ACTIONS


# --- Настройки запуска приложений ---


def launch_without_confirm() -> bool:
    """Разрешён ли запуск приложений без вопроса."""
    return config.load_settings().get("launch_without_confirm") is True


def allowed_apps() -> list[str]:
    """Приложения, которым пользователь разрешил запуск без вопроса."""
    value = config.load_settings().get("allowed_apps")
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


def launch_allowed(path) -> bool:
    """Можно ли запустить этот файл без подтверждения."""
    if launch_without_confirm():
        return True
    try:
        target = _norm(_real(path))
    except (OSError, ValueError):
        return False
    for item in allowed_apps():
        try:
            if _norm(_real(item)) == target:
                return True
        except (OSError, ValueError):
            continue
    return False


# --- Корзина ---


def run_powershell(script: str, timeout: int = 180) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "PowerShell не найден в системе."
    except subprocess.TimeoutExpired:
        return False, "PowerShell не ответил вовремя."
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = lines[-1] if lines else "PowerShell вернул ошибку."
        return False, detail.strip()
    return True, (proc.stdout or "").strip()


def ps_path_literal(path) -> str:
    """Путь для PowerShell: в base64, чтобы спецсимволы не ломали команду."""
    encoded = base64.b64encode(str(path).encode("utf-16-le")).decode("ascii")
    return (
        "[Text.Encoding]::Unicode.GetString("
        f"[Convert]::FromBase64String('{encoded}'))"
    )


def send_to_recycle(path) -> tuple[bool, str]:
    """Отправляет файл или папку в корзину. Постоянного удаления нет."""
    literal = ps_path_literal(path)
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName Microsoft.VisualBasic;"
        f"$p={literal};"
        "$i=Get-Item -LiteralPath $p -Force -ErrorAction Stop;"
        "if($i.PSIsContainer){"
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
        "$p,'OnlyErrorDialogs','SendToRecycleBin')"
        "}else{"
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
        "$p,'OnlyErrorDialogs','SendToRecycleBin')"
        "}"
    )
    ok, message = run_powershell(script)
    return ok, message


# --- Запуск приложений ---


def _start_menu_dirs() -> list[Path]:
    dirs: list[Path] = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("ProgramData")
    if appdata:
        dirs.append(
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
    if programdata:
        dirs.append(
            Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
    return dirs


def _installed_dirs() -> list[Path]:
    """Папки, где обычно стоят установленные программы."""
    dirs: list[Path] = []
    for name in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(name)
        if value:
            dirs.append(Path(value))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Programs")
    return dirs


def _find_installed_exe(wanted: str) -> list[Path]:
    """Ищет файл приложения в папках программ (глубина не больше трёх)."""
    found: list[Path] = []
    for folder in _installed_dirs():
        if not folder.is_dir():
            continue
        for root, dirs, files in os.walk(folder, topdown=True):
            depth = len(Path(root).relative_to(folder).parts)
            if depth >= 3:
                dirs[:] = []
            for name in files:
                if name.lower() == f"{wanted}.exe":
                    found.append(Path(root) / name)
            if len(found) >= 5:
                return found
    return found


def find_app(name: str) -> tuple[Path | None, str | None]:
    """Ищет приложение в меню «Пуск» или в папках программ по имени."""
    wanted = name.strip().lower()
    if not wanted:
        return None, "Пустое имя приложения."
    if wanted.endswith(".lnk"):
        wanted = wanted[:-4]
    exact: list[Path] = []
    fuzzy: list[Path] = []
    for folder in _start_menu_dirs():
        if not folder.is_dir():
            continue
        try:
            items = list(folder.rglob("*"))
        except OSError:
            continue
        for item in items:
            if item.suffix.lower() not in (".lnk", ".exe"):
                continue
            stem = item.stem.lower()
            if stem == wanted:
                exact.append(item)
            elif wanted in stem:
                fuzzy.append(item)
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        names = ", ".join(str(item) for item in exact[:5])
        return None, f"Подходит несколько приложений: {names}. Укажи полный путь."
    if not fuzzy:
        installed = _find_installed_exe(wanted)
        if len(installed) == 1:
            return installed[0], None
        if len(installed) > 1:
            names = ", ".join(str(item) for item in installed[:5])
            return None, f"Подходит несколько приложений: {names}. Укажи полный путь."
    if len(fuzzy) == 1:
        return fuzzy[0], None
    if len(fuzzy) > 1:
        names = ", ".join(str(item) for item in fuzzy[:5])
        return None, f"Подходит несколько приложений: {names}. Укажи полный путь."
    return None, "Не нашёл приложение. Нужен полный путь к exe."


def is_shell_binary(path) -> bool:
    """Запрещённая ли это программа (командная оболочка)."""
    try:
        return Path(str(path)).name.lower() in SHELL_BLOCKLIST
    except (OSError, ValueError):
        return True


def folder_size(path) -> int:
    """Размер папки в байтах."""
    target = Path(str(path))
    if not target.exists():
        return 0
    if target.is_file():
        try:
            return target.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(target, onerror=lambda _err: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def human_size(size: int) -> str:
    """Размер для показа пользователю."""
    value = float(max(0, int(size)))
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            if unit == "Б":
                return f"{int(value)} Б"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


# --- Глобальная память ---
# Правила памяти живут здесь, а не в промте: код нельзя переубедить текстом.

MEMORY_MAX_ENTRIES = 30
MEMORY_MAX_TOTAL_CHARS = 2000
MEMORY_MAX_TEXT_CHARS = 300
MEMORY_MAX_LINES = 8

# Ключи и токены: sk-..., длинные случайные строки, JWT, строки base64.
MEMORY_TOKEN_RE = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_\-]{8,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
    r"|[A-Za-z0-9_\-]{40,})\b"
)
# Пароли и другие секреты по названию поля.
MEMORY_SECRET_FIELD_RE = re.compile(
    r"(?i)\b(?:passwo?rd|passwd|pwd|secret|token|api[_-]?key|access[_-]?key"
    r"|private[_-]?key|пароль|парол[ьи]|ключ|токен)\b\s*[:=]?\s*\S+"
)
# Номер банковской карты: 13-19 цифр с разделителями.
MEMORY_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
# Приватный ключ.
MEMORY_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
# Содержимое .env: несколько строк вида ПЕРЕМЕННАЯ=значение.
MEMORY_ENV_RE = re.compile(r"(?m)^\s*[A-Z][A-Z0-9_]{2,}\s*=\s*\S+")


def validate_memory_text(text) -> tuple[str, str]:
    """Проверяет текст памяти. Возвращает (чистый текст, причина отказа).

    Пустая причина означает, что текст можно сохранять.
    """
    if not isinstance(text, str):
        return "", "Память должна быть текстом."
    cleaned = " ".join(text.split())
    if not cleaned:
        return "", "Пустая память — нечего сохранять."
    if MEMORY_PRIVATE_KEY_RE.search(cleaned):
        return "", "Похоже на приватный ключ. Такое не сохраняю."
    if MEMORY_TOKEN_RE.search(cleaned):
        return "", "Похоже на ключ или токен. Такое не сохраняю."
    if MEMORY_SECRET_FIELD_RE.search(cleaned):
        return "", "Похоже на пароль или секрет. Такое не сохраняю."
    if MEMORY_CARD_RE.search(cleaned):
        return "", "Похоже на номер банковской карты. Такое не сохраняю."
    if len(MEMORY_ENV_RE.findall(cleaned)) >= 2:
        return "", "Похоже на содержимое .env. Такое не сохраняю."
    if len(cleaned.splitlines()) > MEMORY_MAX_LINES:
        return "", (
            "Слишком много строк — это похоже на кусок файла. "
            "В память кладут короткие факты, а не файлы."
        )
    if safety.detect_injection(cleaned):
        return "", "Похоже на инструкцию для модели. Такое не сохраняю."
    if len(cleaned) > MEMORY_MAX_TEXT_CHARS:
        cleaned = cleaned[: MEMORY_MAX_TEXT_CHARS - 1].rstrip() + "…"
    return cleaned, ""
