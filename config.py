# Настройки проекта в одном месте.
# Все секреты берутся только из переменных окружения или из .env.
# Ключи сюда не вписывать.

import json
import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
LOGS_DIR = PROJECT_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"
PROMPT_FILE = PROJECT_DIR / "prompts" / "omega.md"
POLICY_FILE = PROJECT_DIR / "prompts" / "policy.md"
POLICY_HEADER = "--- НЕИЗМЕНЯЕМЫЕ ЗАЩИТНЫЕ ПРАВИЛА ---"

ENV_FILE = PROJECT_DIR / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Читает .env и кладёт значения в окружение, не перезаписывая уже заданные."""
    if not path.exists():
        return

    raw = path.read_bytes()
    # .env может быть сохранён в UTF-8 (с BOM или без) или в cp1251.
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            # Реальная переменная окружения главнее .env
            os.environ.setdefault(name, value)


load_env()

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


# --- Модель ---
MODEL = os.environ.get("MODEL", "claude-haiku-5.5")
MODEL_OPTIONS = (
    "deepseek-v4.1-flash",
    "glm-5.3-flash",
    "gpt-6-luna",
    "claude-haiku-5.5",
)
# Возможности проверены запросами к AITunnel 22.10.2026:
# у всех четырёх моделей работают вызовы инструментов и многоходовые диалоги.
MODEL_CAPS: dict[str, dict[str, object]] = {
    "claude-haiku-5.5": {
        "label": "Haiku 5.5",
        "tools": True,
        "multi_turn": True,
        "warning": "",
    },
    "deepseek-v4.1-flash": {
        "label": "DEEPSEEK V4.1 Flash",
        "tools": True,
        "multi_turn": True,
        "warning": "",
    },
    "glm-5.3-flash": {
        "label": "GLM 5.3 Flash",
        "tools": True,
        "multi_turn": True,
        "warning": "",
    },
    "gpt-6-luna": {
        "label": "GPT 6 Luna",
        "tools": True,
        "multi_turn": True,
        "warning": "",
    },
}
# На случай отказа модели: переключаемся на заведомо рабочую и честно говорим об этом.
FALLBACK_MODEL = "claude-haiku-5.5"
BASE_URL = os.environ.get("BASE_URL", "https://api.aitunnel.ru/v1/")
AITUNNEL_API_KEY = os.environ.get("AITUNNEL_API_KEY", "")


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def current_model() -> str:
    value = str(load_settings().get("model") or "").strip()
    return value if value in MODEL_OPTIONS else MODEL


def model_info(model: str | None = None) -> dict[str, object]:
    """Возможности выбранной модели: инструменты, многоходовость, предупреждения."""
    name = model or current_model()
    info = MODEL_CAPS.get(name)
    if info:
        return dict(info)
    return {
        "label": name,
        "tools": True,
        "multi_turn": True,
        "warning": "Модель не проверялась: возможности неизвестны.",
    }


def policy_text() -> str:
    """Неизменяемая часть промта: защитные правила всегда добавляются."""
    try:
        return POLICY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def default_user_prompt() -> str:
    """Стандартная редактируемая часть промта."""
    try:
        return PROMPT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def current_user_prompt() -> str:
    """Редактируемая часть промта из настроек или стандартная."""
    value = load_settings().get("user_prompt")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default_user_prompt()


def current_system_prompt() -> str:
    """Итоговый системный промт: редактируемая часть + неизменяемые правила."""
    user = current_user_prompt()
    policy = policy_text()
    if not policy:
        return user
    return f"{user}\n\n{POLICY_HEADER}\n{policy}"


def current_sales_module() -> bool:
    """Модуль продаж выключен, пока пользователь явно не включил его в настройках."""
    return load_settings().get("sales_module") is True


def current_memory_enabled() -> bool:
    """Глобальная память включена, пока пользователь её не выключил."""
    return load_settings().get("memory_enabled") is not False


# --- 2ГИС ---
TWOGIS_API_KEY = os.environ.get("TWOGIS_API_KEY", "")
TWOGIS_BASE = "https://catalog.api.2gis.com"

# --- Поиск в интернете ---
# Провайдера меняем одной строкой: stub или yandex.
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "stub").strip().lower()
YANDEX_SEARCH_API_KEY = os.environ.get("YANDEX_SEARCH_API_KEY", "")
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "")
# Регион поиска Яндекса: 225 = Россия, 213 = Москва. Пусто — регион по умолчанию.
YANDEX_REGION = (
    os.environ.get("YANDEX_REGION") or os.environ.get("YANDEX_LR", "")
).strip()

# --- Лимиты цикла ---
MAX_STEPS = int(os.environ.get("MAX_STEPS", "8"))
MAX_TOKENS_PER_REPLY = int(os.environ.get("MAX_TOKENS_PER_REPLY", "2500"))
MAX_TASK_TOKENS = int(os.environ.get("MAX_TASK_TOKENS", "40000"))

# --- Инструменты ---
MAX_FETCH_CHARS = int(os.environ.get("MAX_FETCH_CHARS", "6000"))
MAX_PAGE_BYTES = 800_000
HTTP_TIMEOUT = 20
CHECK_ROBOTS = True

# --- Сообщения (пока заглушка отправки) ---
MAX_MESSAGES_PER_CONTACT = int(os.environ.get("MAX_MESSAGES_PER_CONTACT", "3"))
MAX_NEW_CONTACTS_PER_DAY = int(os.environ.get("MAX_NEW_CONTACTS_PER_DAY", "10"))
MIN_PAUSE_SECONDS = int(os.environ.get("MIN_PAUSE_SECONDS", "30"))

# Честный User-Agent: не изображаем браузер.
USER_AGENT = "Omega/0.2 (personal local assistant; contact: owner)"

# Имена переменных, значения которых нельзя писать в журнал и на экран.
SECRET_ENV_NAMES = (
    "AITUNNEL_API_KEY",
    "TWOGIS_API_KEY",
    "YANDEX_SEARCH_API_KEY",
)


def check_keys() -> list[str]:
    """Возвращает список нужных, но незаполненных ключей (без значений)."""
    missing = []
    if not AITUNNEL_API_KEY:
        missing.append("AITUNNEL_API_KEY")
    if not TWOGIS_API_KEY:
        missing.append("TWOGIS_API_KEY")
    return missing
