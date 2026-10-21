# Черновики сообщений и безопасная "отправка" (пока заглушка).
# Реальной отправки нет: send_message только показывает текст и спрашивает "да/нет".
# Ограничения: лимит сообщений одному человеку, дневной лимит новых контактов,
# список отказов data/optouts.txt.

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import config
import safety


OUTBOX_FILE = "outbox.json"
OPTOUTS_FILE = "optouts.txt"

SENT_STATUSES = ("would_send", "sent")

# Обещания, которые нельзя писать клиенту без подтверждения фактов.
RISKY_PHRASES = (
    "гарантирую",
    "гарантия 100",
    "100%",
    "100 %",
    "бесплатно",
    "лучший в мире",
    "дешевле всех",
    "за 1 день",
    "точно в срок",
)


def _outbox_path() -> Path:
    return config.DATA_DIR / OUTBOX_FILE


def _optouts_path() -> Path:
    return config.DATA_DIR / OPTOUTS_FILE


def _load() -> dict:
    path = _outbox_path()
    if not path.exists():
        return {"messages": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Не удалось прочитать {path.name}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise RuntimeError(f"Файл {path.name} повреждён.")
    return data


def _save(data: dict) -> None:
    """Пишем через временный файл, чтобы не потерять данные при сбое."""
    path = _outbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temp, path)


def _norm(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[\s\-\(\)\[\]]+", "", value)
    return value.lstrip("@+")


def _keys(recipient: str, company: str, contact: str) -> list[str]:
    result = []
    for value in (contact, company, recipient):
        key = _norm(value)
        if key and key not in result:
            result.append(key)
    return result


def _contact_key(message: dict) -> str:
    keys = _keys(
        message.get("recipient", ""),
        message.get("company", ""),
        message.get("contact", ""),
    )
    return keys[0] if keys else ""


def _optouts() -> set[str]:
    path = _optouts_path()
    if not path.exists():
        return set()
    result = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for part in line.split("|"):
            key = _norm(part)
            if key:
                result.add(key)
    return result


def _is_opted_out(recipient: str, company: str, contact: str) -> bool:
    blocked = _optouts()
    return any(key in blocked for key in _keys(recipient, company, contact))


def _messages_for(contact: str, data: dict) -> list[dict]:
    key = _norm(contact)
    if not key:
        return []
    return [
        message
        for message in data["messages"]
        if message.get("status") in SENT_STATUSES and _contact_key(message) == key
    ]


def _sent_today(data: dict) -> list[dict]:
    today = datetime.now().date().isoformat()
    return [
        message
        for message in data["messages"]
        if message.get("status") in SENT_STATUSES
        and str(message.get("sent_at", "")).startswith(today)
    ]


def _clean_text(value: str, limit: int = 3000) -> str:
    value = (value or "").strip()
    return value[:limit]


def draft_message(
    recipient: str,
    text: str,
    channel: str = "telegram",
    company: str = "",
    contact: str = "",
    note: str = "",
) -> dict:
    """Сохраняет черновик. Ничего не отправляет."""
    recipient = _clean_text(recipient, 300)
    text = _clean_text(text)
    channel = _clean_text(channel, 30) or "telegram"
    company = _clean_text(company, 300)
    contact = _clean_text(contact, 300)
    note = _clean_text(note, 500)

    if not recipient:
        return {"error": "Нужно указать получателя (recipient)."}
    if len(text) < 20:
        return {"error": "Текст слишком короткий — напиши нормальное сообщение."}

    contact_key = _keys(recipient, company, contact)[0]

    if _is_opted_out(recipient, company, contact):
        return {
            "error": (
                "Этот человек/компания в списке отказов (data/optouts.txt). "
                "Писать ему нельзя."
            )
        }

    try:
        data = _load()
    except RuntimeError as exc:
        return {"error": str(exc)}

    sent_before = _messages_for(contact_key, data)
    if len(sent_before) >= config.MAX_MESSAGES_PER_CONTACT:
        return {
            "error": (
                f"Этому контакту уже отправлено {len(sent_before)} сообщений "
                f"(лимит {config.MAX_MESSAGES_PER_CONTACT}). Новый черновик не создаю."
            )
        }

    warnings = [
        f"В тексте есть рискованное обещание: «{phrase}». Проверь, что это правда."
        for phrase in RISKY_PHRASES
        if phrase in text.lower()
    ]

    draft_id = uuid.uuid4().hex[:8]
    draft = {
        "id": draft_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "recipient": recipient,
        "company": company,
        "contact": contact,
        "channel": channel,
        "text": text,
        "note": note,
        "status": "draft",
        "confirmed_by_user": False,
        "sent_at": None,
    }
    data["messages"].append(draft)
    _save(data)
    safety.log_event(
        "draft_created",
        draft_id=draft_id,
        channel=channel,
        recipient_len=len(recipient),
        text_len=len(text),
        sent_before=len(sent_before),
    )

    return {
        "draft_id": draft_id,
        "status": "draft",
        "sent": False,
        "preview": text[:500],
        "warnings": warnings,
        "note": "Черновик сохранён. Ничего не отправлено.",
    }


def send_message(draft_id: str) -> dict:
    """Заглушка отправки: показывает черновик, спрашивает подтверждение, НЕ отправляет."""
    try:
        data = _load()
    except RuntimeError as exc:
        return {"error": str(exc)}

    draft = next(
        (item for item in data["messages"] if item.get("id") == draft_id), None
    )
    if draft is None:
        return {"error": f"Черновик {draft_id!r} не найден."}
    if draft.get("status") != "draft":
        return {
            "error": (
                f"У черновика статус {draft.get('status')!r}. "
                "Повторно отправлять нельзя."
            )
        }

    if _is_opted_out(
        draft.get("recipient", ""), draft.get("company", ""), draft.get("contact", "")
    ):
        draft["status"] = "cancelled"
        draft["note"] = "Отмена: контакт в списке отказов."
        _save(data)
        return {"sent": False, "status": "cancelled", "note": "Контакт в списке отказов."}

    contact_key = _contact_key(draft)
    if len(_messages_for(contact_key, data)) >= config.MAX_MESSAGES_PER_CONTACT:
        return {
            "error": (
                f"Лимит {config.MAX_MESSAGES_PER_CONTACT} сообщений одному контакту "
                "исчерпан."
            )
        }

    sent_today = _sent_today(data)
    today_keys = {_contact_key(message) for message in sent_today}
    if (
        contact_key not in today_keys
        and len(today_keys) >= config.MAX_NEW_CONTACTS_PER_DAY
    ):
        return {
            "error": (
                f"Дневной лимит новых контактов ({config.MAX_NEW_CONTACTS_PER_DAY}) "
                "исчерпан. Перенеси отправку на завтра."
            )
        }

    print("\n--- ЧЕРНОВИК СООБЩЕНИЯ ---")
    print(f"Кому:     {draft.get('recipient', '')}")
    if draft.get("company"):
        print(f"Компания: {draft['company']}")
    if draft.get("contact"):
        print(f"Контакт:  {draft['contact']}")
    print(f"Канал:    {draft.get('channel', '')}")
    print("Текст:")
    print(draft.get("text", ""))
    print("--------------------------------")
    print("РЕАЛЬНАЯ ОТПРАВКА НЕ РЕАЛИЗОВАНА: это заглушка.")

    if not safety.ask_confirm("Подтвердить отправку (ничего реально не уйдёт)?"):
        draft["status"] = "cancelled"
        draft["note"] = "Отменено пользователем."
        _save(data)
        safety.log_event("send_cancelled", draft_id=draft_id)
        print("Отменено. Ничего не отправлено.")
        return {
            "sent": False,
            "status": "cancelled",
            "note": "Пользователь не подтвердил отправку.",
        }

    draft["status"] = "would_send"
    draft["confirmed_by_user"] = True
    draft["sent_at"] = datetime.now().isoformat(timespec="seconds")
    _save(data)
    safety.log_event(
        "send_stub",
        draft_id=draft_id,
        channel=draft.get("channel"),
        contact_like=bool(draft.get("contact")),
    )
    print("Подтверждено. ЗАГЛУШКА: сообщение НЕ отправлено.")
    return {
        "sent": False,
        "stub": True,
        "status": "would_send",
        "draft_id": draft_id,
        "note": (
            "Подтверждение получено, но реальная отправка пока не реализована. "
            "Ничего никуда не ушло."
        ),
    }
