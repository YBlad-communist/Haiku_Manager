# Действия Омеги с внешним миром: скачивание файла и снимок экрана.
# Оба действия всегда требуют подтверждения пользователя.

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import config
import policy

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
DOWNLOAD_TIMEOUT = 60
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\- ]+")

DOWNLOAD_TOOL = {
    "type": "function",
    "function": {
        "name": "download_file",
        "description": (
            "Скачать файл по ссылке в папку «Загрузки». "
            "Перед скачиванием пользователь подтверждает действие в окне: "
            "видно ссылку и куда сохранится файл."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Полный адрес файла, начиная с http:// или https://",
                },
                "filename": {
                    "type": "string",
                    "description": "Имя файла для сохранения (необязательно)",
                },
            },
            "required": ["url"],
        },
    },
}

SCREENSHOT_TOOL = {
    "type": "function",
    "function": {
        "name": "screenshot",
        "description": (
            "Сделать снимок экрана и показать его в чате. "
            "Перед снимком пользователь подтверждает действие в окне."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

ACTIONS_TOOLS = [DOWNLOAD_TOOL, SCREENSHOT_TOOL]


def _safe_name(value: str) -> str:
    name = SAFE_NAME_RE.sub("_", str(value or "").strip())
    name = name.strip(" ._")
    if not name:
        name = "download"
    return name[:120]


def _downloads_dir() -> Path:
    folder = Path(os.path.expanduser("~")) / "Downloads"
    if not folder.is_dir():
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def _unique_path(folder: Path, name: str) -> Path:
    target = folder / name
    if not target.exists():
        return target
    stem, suffix = os.path.splitext(name)
    index = 2
    while True:
        candidate = folder / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _is_local_host(host: str) -> bool:
    """Локальные адреса Омега не скачивает: это серверы и служебные службы."""
    name = str(host or "").strip().lower().strip("[]")
    if not name:
        return True
    if name in ("localhost", "0.0.0.0", "::1", "::"):
        return True
    if name.startswith("127.") or name.startswith("10.") or name.startswith("192.168."):
        return True
    if name.endswith(".local") or name.endswith(".internal"):
        return True
    if name.startswith("172."):
        try:
            second = int(name.split(".")[1])
        except (IndexError, ValueError):
            return False
        if 16 <= second <= 31:
            return True
    return False


def download_file(url: str, filename: str = "") -> dict:
    """Скачивает файл в папку «Загрузки» после подтверждения."""
    raw = str(url or "").strip()
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"error": "Нужен полный адрес файла http:// или https://."}
    if _is_local_host(parsed.hostname or ""):
        return {"error": "Локальные адреса скачивать нельзя."}

    name = _safe_name(filename) if filename else _safe_name(
        Path(urllib.parse.unquote(parsed.path)).name or "download"
    )
    folder = _downloads_dir()
    target = _unique_path(folder, name)

    answer = policy.confirm(
        "download_file",
        "Скачать файл?",
        f"Скачать файл?\n{raw}",
        details=(
            f"Сохранить сюда:\n{target}\n\n"
            f"Ограничение: {policy.human_size(MAX_DOWNLOAD_BYTES)}"
        ),
    )
    if not answer["approved"]:
        return {"cancelled": True, "url": raw}

    request = urllib.request.Request(
        raw,
        headers={"User-Agent": config.USER_AGENT},
    )
    written = 0
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
            with open(target, "wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        handle.close()
                        target.unlink(missing_ok=True)
                        return {
                            "error": (
                                "Файл слишком большой: больше "
                                f"{policy.human_size(MAX_DOWNLOAD_BYTES)}."
                            )
                        }
                    handle.write(chunk)
    except urllib.error.HTTPError as exc:
        target.unlink(missing_ok=True)
        return {"error": f"Сервер ответил ошибкой {exc.code}."}
    except urllib.error.URLError as exc:
        target.unlink(missing_ok=True)
        return {"error": f"Не удалось скачать: {exc.reason}"}
    except OSError as exc:
        target.unlink(missing_ok=True)
        return {"error": f"Не удалось сохранить файл: {exc}"}

    return {
        "url": raw,
        "path": str(target),
        "size": written,
        "size_text": policy.human_size(written),
    }


def _screenshot_path() -> Path:
    folder = config.DATA_DIR / "screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return folder / f"shot-{stamp}.png"


def screenshot() -> dict:
    """Снимок экрана: сохраняется в data/screenshots и показывается в чате."""
    target = _screenshot_path()
    answer = policy.confirm(
        "screenshot",
        "Сделать снимок экрана?",
        "Сделать снимок экрана?",
        details=f"Снимок сохранится сюда:\n{target}",
    )
    if not answer["approved"]:
        return {"cancelled": True}

    literal = policy.ps_path_literal(target)
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
        "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height);"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size);"
        f"$bmp.Save({literal},[System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose();$bmp.Dispose();"
        f"Write-Output ($b.Width.ToString()+'x'+$b.Height.ToString());"
    )
    ok, message = policy.run_powershell(script)
    if not ok or not target.exists():
        return {"error": f"Не удалось сделать снимок экрана: {message}"}
    size = policy.human_size(target.stat().st_size)
    return {
        "path": str(target),
        "file": target.name,
        "size": target.stat().st_size,
        "size_text": size,
        "resolution": message,
    }


HANDLERS = {
    "download_file": download_file,
    "screenshot": screenshot,
}
