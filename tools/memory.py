# Инструмент глобальной памяти.
# Сам инструмент ничего не сохраняет: он просит пользователя подтвердить запись.

import memory
import policy


MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "memory_propose",
        "description": (
            "Предложить сохранить сведения о пользователе в память. "
            "Инструмент сам ничего не сохраняет: пользователь увидит карточку "
            "«Запомнить: …?» и решит, сохранять ли. "
            "Сохраняй только короткие факты о самом пользователе: имя, город, "
            "привычки, предпочтения, постоянные задачи. "
            "Не сохраняй чужие данные, ключи, пароли, номера карт и содержимое файлов. "
            "Если сведения уже сохранены, не повторяй их."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Один короткий факт о пользователе, до 300 символов"
                    ),
                },
            },
            "required": ["text"],
        },
    },
}


def memory_propose(text: str) -> dict:
    """Показывает карточку «Запомнить: …?» и сохраняет только после «Да»."""
    cleaned, reason = policy.validate_memory_text(text)
    if reason:
        return {"error": f"Не сохранил: {reason}"}

    answer = policy.confirm(
        "memory_propose",
        "Запомнить?",
        cleaned,
        details=(
            "Текст попадёт в память и будет уходить модели при каждом запросе. "
            "Можно изменить его перед сохранением."
        ),
    )
    if not answer["approved"]:
        return {"cancelled": True, "text": cleaned}

    edited = str((answer.get("answer") or {}).get("text") or "").strip()
    final_text = edited or cleaned
    again, reason = policy.validate_memory_text(final_text)
    if reason:
        return {"error": f"Не сохранил: {reason}"}

    entry, error = memory.add_entry(again)
    if entry is None:
        return {"error": error}
    return {
        "saved": True,
        "id": entry["id"],
        "text": entry["text"],
        "date": entry["date"],
        "count": len(memory.load_entries()),
    }
