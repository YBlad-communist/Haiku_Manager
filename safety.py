# Вспомогательные функции безопасности:
# - журнал вызовов без секретов,
# - маскировка ключей,
# - поиск попыток "промпт-инъекций" в чужом тексте,
# - подтверждение в консоли.

import json
import os
import re
from datetime import datetime
from typing import Any

import config


# Фразы, которыми со страниц пытаются управлять моделью.
# Это только вспомогательная защита: главное — у агента нет опасных инструментов.
INJECTION_PATTERNS = [
    r"забудь\s+(все\s+)?(предыдущ|прошл|свои|инструкц|правил)",
    r"игнорируй\s+(все\s+)?(предыдущ|прошл|инструкц|правил|указан)",
    r"не\s+обращай\s+внимания\s+на\s+(инструкц|правил)",
    r"новые\s+инструкции",
    r"системн\w*\s+(промпт|инструкц)",
    r"ignore\s+(all\s+)?(previous|prior|above)",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"system\s+prompt",
    r"new\s+instructions",
    r"ты\s+теперь\s+",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+",
]
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)

# Что-то похожее на ключ или токен.
_KEY_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|[A-Za-z0-9_\-]{32,})")

# Слова в аргументах, значения которых точно секретные.
# Важно не замаскировать служебные счётчики вроде prompt_tokens.
_SECRET_ARG_NAMES = ("key", "apikey", "api_key", "token", "secret", "password")


def _is_secret_arg(name: str) -> bool:
    name = str(name).lower()
    if name in _SECRET_ARG_NAMES:
        return True
    return name.endswith(("_key", "_token", "_secret", "password"))


def _secret_values() -> list[str]:
    values = []
    for name in config.SECRET_ENV_NAMES:
        value = os.environ.get(name, "")
        if len(value) >= 8:
            values.append(value)
    return values


def redact(text: str) -> str:
    """Убирает из строки ключи и токены."""
    if not isinstance(text, str):
        text = str(text)
    for value in _secret_values():
        text = text.replace(value, "***")
    return _KEY_RE.sub("***", text)


def redact_obj(obj: Any) -> Any:
    """Рекурсивно маскирует секреты в словарях и списках."""
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if _is_secret_arg(key):
                result[key] = "***"
            else:
                result[key] = redact_obj(value)
        return result
    if isinstance(obj, list):
        return [redact_obj(item) for item in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


def shorten_obj(obj: Any, max_str: int = 300) -> Any:
    """Обрезает длинные строки, чтобы журнал не разрастался."""
    if isinstance(obj, dict):
        return {key: shorten_obj(value, max_str) for key, value in obj.items()}
    if isinstance(obj, list):
        return [shorten_obj(item, max_str) for item in obj]
    if isinstance(obj, str) and len(obj) > max_str:
        return obj[:max_str] + "..."
    return obj


def log_event(event: str, **fields: Any) -> None:
    """Пишет строку JSON в logs/agent.log. Без ключей и без текстов задач."""
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "event": event,
    }
    record.update(shorten_obj(redact_obj(fields)))
    try:
        with open(config.LOGS_DIR / "agent.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Журнал не должен ломать работу агента.
        pass


def detect_injection(text: str) -> str | None:
    """Возвращает найденную подозрительную фразу или None."""
    if not text:
        return None
    match = _INJECTION_RE.search(text)
    return match.group(0) if match else None


def ask_confirm(question: str) -> bool:
    """Спрашивает подтверждение в консоли. Всё, что не 'да', считается отказом."""
    answer = input(f"{question} [да/нет]: ").strip().lower()
    return answer in ("да", "д", "yes", "y")
