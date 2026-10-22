# Напоминания Омеги: простые напоминания по времени.
# Файл data/reminders.json не попадает в git. Уведомление показывает Electron.

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import config
import policy


MAX_REMINDERS = 50
MAX_TEXT_CHARS = 200
MAX_MINUTES = 60 * 24 * 30


def reminders_path() -> Path:
    override = os.environ.get("OMEGA_REMINDERS_FILE")
    return Path(override) if override else config.DATA_DIR / "reminders.json"


def load_reminders() -> list[dict]:
    """Читает напоминания. Битый файл — пустой список."""
    try:
        data = json.loads(reminders_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    items: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        at = str(item.get("at") or "").strip()
        if not text or not at:
            continue
        items.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex[:12]),
                "text": text[:MAX_TEXT_CHARS],
                "at": at[:40],
                "done": bool(item.get("done")),
                "created_at": str(item.get("created_at") or datetime.now().isoformat(timespec="seconds"))[:40],
            }
        )
    return items


def save_reminders(items: list[dict]) -> None:
    path = reminders_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(items[-MAX_REMINDERS:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, path)


def add_reminder(text: str, minutes: float) -> tuple[dict | None, str]:
    """Создаёт напоминание. Возвращает (напоминание, причина отказа)."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return None, "Пустое напоминание — нечего напоминать."
    if len(cleaned) > MAX_TEXT_CHARS:
        return None, f"Слишком длинный текст: максимум {MAX_TEXT_CHARS} символов."
    if policy.is_secret_text(cleaned):
        return None, "Похоже на пароль или ключ. Такое в напоминание не кладу."
    try:
        delay = float(minutes)
    except (TypeError, ValueError):
        return None, "Нужно число минут: например, 30."
    if delay <= 0:
        return None, "Срок должен быть больше нуля."
    if delay > MAX_MINUTES:
        return None, f"Слишком далеко: максимум {MAX_MINUTES // 60 // 24} дней."
    when = datetime.now() + timedelta(minutes=delay)
    items = load_reminders()
    pending = [item for item in items if not item["done"]]
    if len(pending) >= MAX_REMINDERS:
        return None, f"Напоминаний уже {MAX_REMINDERS}. Удали лишние."
    item = {
        "id": uuid.uuid4().hex[:12],
        "text": cleaned,
        "at": when.isoformat(timespec="seconds"),
        "done": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.append(item)
    save_reminders(items)
    return item, ""


def delete_reminder(reminder_id: str) -> bool:
    """Удаляет напоминание."""
    items = load_reminders()
    remaining = [item for item in items if item.get("id") != reminder_id]
    if len(remaining) == len(items):
        return False
    save_reminders(remaining)
    return True


def mark_done(reminder_id: str) -> bool:
    """Отмечает напоминание как сработавшее."""
    items = load_reminders()
    found = False
    for item in items:
        if item.get("id") == reminder_id:
            item["done"] = True
            found = True
    if found:
        save_reminders(items)
    return found


def due_reminders(now: datetime | None = None) -> list[dict]:
    """Напоминания, время которых наступило."""
    moment = now or datetime.now()
    result = []
    for item in load_reminders():
        if item.get("done"):
            continue
        try:
            when = datetime.fromisoformat(item["at"])
        except ValueError:
            continue
        if when <= moment:
            result.append(item)
    return result


def pending_reminders() -> list[dict]:
    """Активные напоминания, ближайшие первыми."""
    items = [item for item in load_reminders() if not item.get("done")]
    items.sort(key=lambda item: str(item.get("at") or ""))
    return items
