# Настройки проекта в одном месте.
# Все секреты берутся только из переменных окружения или из .env.
# Ключи сюда не вписывать.

import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
LOGS_DIR = PROJECT_DIR / "logs"

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
BASE_URL = os.environ.get("BASE_URL", "https://api.aitunnel.ru/v1/")
AITUNNEL_API_KEY = os.environ.get("AITUNNEL_API_KEY", "")

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
USER_AGENT = "HaikuManager/0.1 (personal research assistant; contact: owner)"

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
