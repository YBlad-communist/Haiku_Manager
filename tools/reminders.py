# Инструмент напоминаний: напомнить через N минут.
# Создание требует подтверждения пользователя.

import reminders
import policy


ADD_REMINDER_TOOL = {
    "type": "function",
    "function": {
        "name": "add_reminder",
        "description": (
            "Напомнить пользователю через указанное число минут. "
            "Инструмент показывает карточку с подтверждением: текст "
            "напоминания и время. Уведомление придёт в трее, пока Омега запущена. "
            "Пользуйся, когда пользователь прямо просит напомнить. "
            "Не выдумывай сроки: бери их из сообщения пользователя."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Что напомнить, до 200 символов",
                },
                "minutes": {
                    "type": "integer",
                    "description": "Через сколько минут напомнить (1 — через минуту)",
                    "minimum": 1,
                    "maximum": 43200,
                },
            },
            "required": ["text", "minutes"],
        },
    },
}

LIST_REMINDERS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_reminders",
        "description": "Показать активные напоминания пользователя с временем.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

REMINDER_TOOLS = [ADD_REMINDER_TOOL, LIST_REMINDERS_TOOL]


def add_reminder(text: str, minutes: int) -> dict:
    """Создаёт напоминание после подтверждения пользователя."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return {"error": "Пустое напоминание — нечего напоминать."}
    try:
        delay = int(minutes)
    except (TypeError, ValueError):
        return {"error": "Нужно целое число минут."}
    if delay <= 0:
        return {"error": "Срок должен быть больше нуля."}

    answer = policy.confirm(
        "add_reminder",
        "Напомнить?",
        f"Напомнить через {delay} мин: {cleaned}",
        details="Уведомление придёт в трее, пока Омега запущена.",
    )
    if not answer["approved"]:
        return {"cancelled": True, "text": cleaned}

    item, error = reminders.add_reminder(cleaned, delay)
    if item is None:
        return {"error": error}
    return {
        "saved": True,
        "id": item["id"],
        "text": item["text"],
        "at": item["at"],
        "in_minutes": delay,
    }


def list_reminders() -> dict:
    """Активные напоминания."""
    items = reminders.pending_reminders()
    return {
        "count": len(items),
        "reminders": [
            {"id": item["id"], "text": item["text"], "at": item["at"]} for item in items
        ],
    }


HANDLERS = {
    "add_reminder": add_reminder,
    "list_reminders": list_reminders,
}
