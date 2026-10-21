# Воркер одной задачи. Запускается сервером как отдельный процесс.
# Общается с сервером строками JSON: события в stdout, команды в stdin.
# Отдельный процесс нужен, чтобы кнопка «Стоп» могла жёстко прервать задачу.

import json
import queue
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# stdout занят протоколом событий. Всё остальное (в том числе print из
# инструментов) уводим в stderr, чтобы не ломать JSON-поток.
EVENT_STREAM = sys.stdout
sys.stdout = sys.stderr
for stream in (EVENT_STREAM, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import agent  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402
import safety  # noqa: E402
import tools  # noqa: E402
from tools import messages  # noqa: E402


def emit(payload: dict) -> None:
    EVENT_STREAM.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    EVENT_STREAM.flush()


def _short(value: str, limit: int = 400) -> str:
    value = value.replace("\n", " ")
    return value if len(value) <= limit else value[:limit] + "..."


COMMANDS: "queue.Queue[dict]" = queue.Queue()


def _read_commands() -> None:
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(command, dict):
                COMMANDS.put(command)
    finally:
        COMMANDS.put({"type": "shutdown"})


threading.Thread(target=_read_commands, daemon=True).start()


def request_confirmation(payload: dict) -> dict:
    """Отправляет запрос в окно и ждёт ответа. Процесс может быть убит стопом."""
    confirm_id = uuid.uuid4().hex[:12]
    emit({"type": "confirm", "id": confirm_id, **payload})
    while True:
        command = COMMANDS.get()
        if command.get("type") == "shutdown":
            raise RuntimeError("Приложение закрыло соединение с воркером.")
        if command.get("type") == "confirm_answer" and command.get("id") == confirm_id:
            return command


_AUTO_CONFIRM: bool | None = None


def ask_confirm(question: str) -> bool:
    """Замена консольного подтверждения из safety.py."""
    if _AUTO_CONFIRM is not None:
        return _AUTO_CONFIRM
    answer = request_confirmation(
        {
            "kind": "generic",
            "title": "Подтвердить действие?",
            "text": question,
            "channel": "",
            "today": 0,
            "limit": 0,
        }
    )
    return answer.get("action") in ("approve", "edit")


safety.ask_confirm = ask_confirm


_ORIGINAL_SEND = messages.send_message


def ui_send_message(draft_id: str) -> dict:
    """Диалог подтверждения вместо консоли. Логику проверок оставляем оригиналу."""
    try:
        data = messages._load()
    except RuntimeError as exc:
        return {"error": str(exc)}

    draft = next(
        (item for item in data["messages"] if item.get("id") == draft_id), None
    )
    if draft is None or draft.get("status") != "draft":
        # Оригинал вернёт понятную ошибку и не будет ничего спрашивать.
        return _ORIGINAL_SEND(draft_id)

    if messages._is_opted_out(
        draft.get("recipient", ""), draft.get("company", ""), draft.get("contact", "")
    ):
        return _ORIGINAL_SEND(draft_id)

    contact_key = messages._contact_key(draft)
    if len(messages._messages_for(contact_key, data)) >= config.MAX_MESSAGES_PER_CONTACT:
        return _ORIGINAL_SEND(draft_id)

    sent_today = messages._sent_today(data)
    today_keys = {messages._contact_key(item) for item in sent_today}
    if (
        contact_key not in today_keys
        and len(today_keys) >= config.MAX_NEW_CONTACTS_PER_DAY
    ):
        return _ORIGINAL_SEND(draft_id)

    today = len(today_keys)
    answer = request_confirmation(
        {
            "kind": "send_message",
            "title": "Отправить сообщение?",
            "draft_id": draft_id,
            "recipient": draft.get("recipient", ""),
            "company": draft.get("company", ""),
            "contact": draft.get("contact", ""),
            "channel": draft.get("channel", ""),
            "text": draft.get("text", ""),
            "today": today,
            "limit": config.MAX_NEW_CONTACTS_PER_DAY,
        }
    )

    action = answer.get("action")
    accepted = action in ("approve", "edit")

    if accepted and action == "edit":
        text = messages._clean_text(str(answer.get("text") or ""))
        if len(text) < 20:
            return {
                "error": (
                    "Новый текст слишком короткий (минимум 20 символов). "
                    "Черновик не изменён."
                )
            }
        draft["text"] = text
        draft["edited_by_user"] = True
        messages._save(data)
        emit({"type": "draft_edited", "draft_id": draft_id, "text": text})

    global _AUTO_CONFIRM
    _AUTO_CONFIRM = accepted
    try:
        return _ORIGINAL_SEND(draft_id)
    finally:
        _AUTO_CONFIRM = None


tools.HANDLERS["send_message"] = ui_send_message


_ORIGINAL_EXECUTE = agent.execute


def ui_execute(name: str, arguments: dict) -> dict:
    """Показывает окну вызов инструмента и его результат."""
    safe_args = json.dumps(
        safety.redact_obj(arguments), ensure_ascii=False, default=str
    )
    emit({"type": "tool", "name": name, "args": _short(safe_args, 400)})
    result = _ORIGINAL_EXECUTE(name, arguments)
    ok = isinstance(result, dict) and "error" not in result
    summary = (
        agent._summary(result) if isinstance(result, dict) else _short(str(result), 300)
    )
    emit({"type": "tool_result", "name": name, "ok": ok, "summary": summary})
    return result


agent.execute = ui_execute


_ORIGINAL_CHAT = llm.LLM.chat


def ui_chat(self, *args, **kwargs):
    """Перед вызовом модели сообщаем номер шага, после — токены и цену."""
    emit(
        {
            "type": "step",
            "step": self.calls + 1,
            "max_steps": config.MAX_STEPS,
        }
    )
    response = _ORIGINAL_CHAT(self, *args, **kwargs)
    emit(
        {
            "type": "usage",
            "tokens": self.total_tokens,
            "cost": round(self.total_cost, 4),
            "step": self.calls,
            "max_steps": config.MAX_STEPS,
        }
    )
    return response


llm.LLM.chat = ui_chat


def run_task(task: str) -> None:
    try:
        result = agent.run(task, verbose=False)
        emit({"type": "final", **result})
    except Exception as exc:  # noqa: BLE001
        safety.log_event("ui_worker_error", error=safety.redact(str(exc))[:500])
        traceback.print_exc(file=sys.stderr)
        emit(
            {
                "type": "final",
                "answer": f"Ошибка: {safety.redact(str(exc))}",
                "steps": 0,
                "tokens": 0,
                "cost": 0.0,
                "stopped_reason": "error",
            }
        )


def selftest() -> None:
    """Проверка протокола без модели и без денег."""
    emit({"type": "step", "step": 1, "max_steps": config.MAX_STEPS})
    emit(
        {
            "type": "tool",
            "name": "search_companies_2gis",
            "args": '{"query": "кофейня", "city": "Казань"}',
        }
    )
    time.sleep(0.2)
    emit(
        {
            "type": "tool_result",
            "name": "search_companies_2gis",
            "ok": True,
            "summary": "компаний: 2",
        }
    )
    emit(
        {
            "type": "usage",
            "tokens": 100,
            "cost": 0.01,
            "step": 1,
            "max_steps": config.MAX_STEPS,
        }
    )
    answer = request_confirmation(
        {
            "kind": "send_message",
            "title": "Отправить сообщение?",
            "draft_id": "selftest",
            "recipient": "Кофейня «Тест»",
            "company": "ООО Тест",
            "contact": "@test",
            "channel": "telegram",
            "text": (
                "Здравствуйте! Это тестовый черновик для проверки диалога. "
                "Ничего никуда не отправляется."
            ),
            "today": 0,
            "limit": config.MAX_NEW_CONTACTS_PER_DAY,
        }
    )
    if answer.get("action") in ("approve", "edit"):
        text = (
            "Тест пройден: диалог подтверждения работает, статус would_send, "
            "реальной отправки нет."
        )
        reason = "done"
    else:
        text = "Тест: подтверждение отклонено, ничего не отправлено."
        reason = "cancelled"
    emit(
        {
            "type": "final",
            "answer": text,
            "steps": 1,
            "tokens": 100,
            "cost": 0.01,
            "stopped_reason": reason,
        }
    )


def main() -> int:
    emit({"type": "ready"})
    if "--selftest" in sys.argv:
        selftest()
        return 0

    while True:
        command = COMMANDS.get()
        if command.get("type") == "shutdown":
            return 0
        if command.get("type") == "run":
            run_task(str(command.get("task") or ""))
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
