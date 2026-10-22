# Вложения в чат: приём, обработка и хранение.
# Файлы лежат в data/attachments/<id чата>/, в чате хранятся только ссылки.
# Правила приёма — в policy.py, чтение документов — в docs.py, OCR — в tools/ocr.py.

import base64
import io
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import config
import docs
import policy


def attachments_root() -> Path:
    """Корень папки вложений."""
    override = os.environ.get("OMEGA_ATTACHMENTS_DIR")
    return Path(override) if override else config.DATA_DIR / "attachments"


def attachments_dir(chat_id: str) -> Path:
    """Папка вложений чата. Имя папки очищено, чтобы не уйти из data/."""
    return attachments_root() / policy.safe_chat_folder(chat_id)


def ensure_dir(chat_id: str) -> Path:
    folder = attachments_dir(chat_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def delete_chat_attachments(chat_id: str) -> bool:
    """Стирает вложения чата с диска."""
    folder = attachments_dir(chat_id)
    if not folder.exists():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return True


def clear_all_attachments() -> int:
    """Стирает все вложения. Возвращает число удалённых папок."""
    root = attachments_root()
    if not root.is_dir():
        return 0
    count = 0
    for folder in root.iterdir():
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            count += 1
    return count


def decode_payload(data: str) -> bytes:
    """Разбирает base64 из запроса."""
    raw = str(data or "")
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    padding = "=" * (-len(raw) % 4)
    return base64.b64decode(raw + padding)


def _decode_text(raw: bytes) -> tuple[str, bool]:
    """Читает текст без выполнения. Возвращает (текст, обрезан ли)."""
    truncated = False
    limit = policy.MAX_TEXT_BYTES
    if len(raw) > limit:
        raw = raw[:limit]
        truncated = True
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding), truncated
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), truncated


def process_image(raw: bytes) -> dict:
    """Уменьшает картинку, сжимает и убирает EXIF. Возвращает (png, размеры)."""
    try:
        from PIL import Image, ImageOps  # noqa: PLC0415
    except ImportError:
        return {"error": "Нужен Pillow для обработки картинок."}
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            picture = ImageOps.exif_transpose(source)
            # Новый снимок без метаданных: EXIF и прочее не копируются.
            clean = Image.new("RGB", picture.size, (255, 255, 255))
            if picture.mode in ("RGBA", "LA", "P"):
                clean.paste(picture, mask=picture.getchannel("A"))
            else:
                clean.paste(picture.convert("RGB"))
            width, height = clean.size
            longest = max(width, height)
            if longest > policy.IMAGE_LONG_SIDE:
                ratio = policy.IMAGE_LONG_SIDE / longest
                clean = clean.resize(
                    (max(1, int(width * ratio)), max(1, int(height * ratio))),
                    Image.LANCZOS,
                )
            buffer = io.BytesIO()
            clean.save(buffer, format="PNG", optimize=True)
            data = buffer.getvalue()
            thumb = clean.copy()
            thumb.thumbnail((policy.IMAGE_THUMB_SIDE, policy.IMAGE_THUMB_SIDE))
            thumb_buffer = io.BytesIO()
            thumb.save(thumb_buffer, format="PNG", optimize=True)
            return {
                "data": data,
                "thumb": thumb_buffer.getvalue(),
                "width": clean.width,
                "height": clean.height,
                "original_width": width,
                "original_height": height,
                "resized": longest > policy.IMAGE_LONG_SIDE,
            }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Не удалось обработать картинку: {exc}"}


def process_text(raw: bytes) -> dict:
    """Читает текстовый файл как данные."""
    text, truncated = _decode_text(raw)
    return {
        "text": text,
        "truncated": truncated,
        "chars": len(text),
        "bytes": len(raw),
    }


def process_document(raw: bytes, name: str) -> dict:
    """Читает документ через общий код docs.py."""
    folder = config.DATA_DIR / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / f"read-{uuid.uuid4().hex[:12]}{Path(name).suffix.lower()}"
    try:
        temp.write_bytes(raw)
        result = docs.read_any(temp)
    finally:
        temp.unlink(missing_ok=True)
    return result


def save_attachment(
    chat_id: str,
    name: str,
    raw: bytes,
    kind: str,
) -> tuple[dict | None, str]:
    """Сохраняет вложение и возвращает (метаданные, ошибка)."""
    safe_name = policy.safe_attachment_name(name)
    suffix = Path(safe_name).suffix.lower()
    attachment_id = uuid.uuid4().hex[:12]
    folder = ensure_dir(chat_id)

    if kind == "image":
        processed = process_image(raw)
        if "error" in processed:
            return None, processed["error"]
        main_name = f"{attachment_id}.png"
        thumb_name = f"{attachment_id}-thumb.png"
        (folder / main_name).write_bytes(processed["data"])
        (folder / thumb_name).write_bytes(processed["thumb"])
        return (
            {
                "id": attachment_id,
                "name": safe_name,
                "kind": "image",
                "size": len(processed["data"]),
                "original_size": len(raw),
                "width": processed["width"],
                "height": processed["height"],
                "original_width": processed["original_width"],
                "original_height": processed["original_height"],
                "resized": processed["resized"],
                "file": main_name,
                "thumb": thumb_name,
                "tokens": policy.estimate_image_tokens(
                    processed["width"], processed["height"]
                ),
                "text": "",
                "truncated": False,
            },
            "",
        )

    if kind == "text":
        processed = process_text(raw)
        text = processed["text"]
        note = ""
        if processed["truncated"]:
            note = "\n\n[файл обрезан: прочитаны первые 200 КБ]"
        stored = text + note
        main_name = f"{attachment_id}{suffix}"
        (folder / main_name).write_text(stored, encoding="utf-8")
        return (
            {
                "id": attachment_id,
                "name": safe_name,
                "kind": "text",
                "size": len(stored.encode("utf-8")),
                "original_size": len(raw),
                "file": main_name,
                "thumb": "",
                "tokens": policy.estimate_text_tokens(stored),
                "text": stored,
                "truncated": processed["truncated"],
            },
            "",
        )

    if kind == "document":
        result = process_document(raw, safe_name)
        if "error" in result:
            return None, result["error"]
        text = str(result.get("text") or "")
        note = ""
        if result.get("truncated"):
            note = "\n\n[документ обрезан]"
        stored = text + note
        main_name = f"{attachment_id}{suffix}"
        (folder / main_name).write_text(stored, encoding="utf-8")
        return (
            {
                "id": attachment_id,
                "name": safe_name,
                "kind": "document",
                "size": len(stored.encode("utf-8")),
                "original_size": len(raw),
                "file": main_name,
                "thumb": "",
                "tokens": policy.estimate_text_tokens(stored),
                "text": stored,
                "truncated": bool(result.get("truncated")),
            },
            "",
        )

    return None, "Такой тип вложения не поддерживается."


def attachment_path(chat_id: str, file_name: str) -> Path:
    """Путь к файлу вложения. Имя проверяется, чтобы не выйти из папки."""
    safe = Path(str(file_name or "")).name
    if not safe or safe != file_name:
        raise ValueError("Недопустимое имя файла вложения.")
    folder = attachments_dir(chat_id)
    target = folder / safe
    if target.parent != folder:
        raise ValueError("Недопустимый путь вложения.")
    return target


def read_attachment_bytes(chat_id: str, file_name: str) -> bytes:
    return attachment_path(chat_id, file_name).read_bytes()


def ocr_attachment(chat_id: str, attachment_id: str) -> tuple[str, str]:
    """Распознаёт текст в картинке-вложении. Возвращает (текст, ошибка)."""
    folder = attachments_dir(chat_id)
    target = folder / f"{attachment_id}.png"
    if not target.is_file():
        return "", "Картинка не найдена."
    from tools import ocr  # noqa: PLC0415 — чтобы не тянуть движок при импорте

    text, error = ocr.ocr_text(target)
    if error:
        return "", error
    stored = text
    (folder / f"{attachment_id}.txt").write_text(stored, encoding="utf-8")
    return stored, ""


def build_block(attachments: list[dict]) -> str:
    """Собирает блок с содержимым вложений для запроса к модели."""
    if not attachments:
        return ""
    parts = [
        policy.ATTACHMENT_BLOCK_HEADER,
        policy.ATTACHMENT_BLOCK_NOTE,
    ]
    for item in attachments:
        name = policy.safe_attachment_name(str(item.get("name") or "файл"))
        if item.get("kind") == "image":
            parts.append(f"[изображение: {name}]")
            continue
        text = str(item.get("text") or "")
        parts.append(f"[файл: {name}]\n{text}")
    return "\n\n".join(parts)


def summary_line(attachment: dict) -> str:
    """Короткая пометка вложения для истории чата."""
    name = policy.safe_attachment_name(str(attachment.get("name") or "файл"))
    if attachment.get("kind") == "image":
        return f"[изображение: {name}]"
    return f"[файл: {name}]"


def write_meta(chat_id: str, items: list[dict]) -> None:
    """Дополнительный файл с метаданными вложений чата."""
    folder = ensure_dir(chat_id)
    path = folder / "attachments.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temp, path)


def read_meta(chat_id: str) -> list[dict]:
    path = attachments_dir(chat_id) / "attachments.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def created_at() -> str:
    return datetime.now().isoformat(timespec="seconds")
