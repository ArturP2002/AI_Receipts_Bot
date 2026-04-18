import os


def _env_int(key: str, default: int) -> int:
    """Целое из окружения; пустая строка и мусор не роняют импорт модуля."""
    raw = os.getenv(key)
    if raw is None:
        return default
    s = str(raw).strip()
    if not s:
        return default
    try:
        return int(s)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    s = str(raw).strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


# Единственный способ оплаты в боте — Telegram Stars (код валюты Bot API).
TELEGRAM_STARS_CURRENCY = "XTR"

BASE_FREE_RECIPE_OPENS = 10
REFERRAL_BONUS_OPENS = 10
FREE_SHOW_MORE_COUNT = 3
RECIPE_STAR_PRICE = _env_int("RECIPE_STAR_PRICE", 15)
SHOW_MORE_STAR_PRICE = _env_int("SHOW_MORE_STAR_PRICE", 10)
# Покупка подписки за Telegram Stars (XTR), длительность — SUBSCRIPTION_DEFAULT_DAYS
SUBSCRIPTION_STAR_PRICE = _env_int("SUBSCRIPTION_STAR_PRICE", 100)
BOT_USERNAME = os.getenv("BOT_USERNAME", "kitchen_world_bot")
LAPSE_NOTIFY_DAYS = (1, 5, 10, 20, 30)
ARCHIVE_GRACE_DAYS = 30
SUBSCRIPTION_DEFAULT_DAYS = max(1, _env_int("SUBSCRIPTION_DEFAULT_DAYS", 30))
# Окно «напоминание после окончания» (календарные дни после даты окончания), если бот не работал в нужный день
SUBSCRIPTION_POST_EXPIRY_REMIND_DAYS = max(
    1, min(14, _env_int("SUBSCRIPTION_POST_EXPIRY_REMIND_DAYS", 3))
)

# OpenAI (текст + картинки). Модели можно сменить через env — см. services/openai_ai.py
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "dall-e-3")
OPENAI_IMAGE_SIZE = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024")
# Подбор по продуктам / по названию блюда — только через OpenAI (локальная база для подбора не используется).
PRODUCTS_AI_MODE = "always"
AI_RECIPES_PER_REQUEST = max(1, min(5, _env_int("AI_RECIPES_PER_REQUEST", 3)))
OPENAI_RECIPE_MAX_TOKENS = max(600, _env_int("OPENAI_RECIPE_MAX_TOKENS", 2600))
# Картинки к рецептам: sync — ждём все; async — в фоне (быстрее ответ пользователю); off — не генерировать
_rim = os.getenv("RECIPE_IMAGES_MODE", "async").strip().lower()
RECIPE_IMAGES_MODE = _rim if _rim in ("sync", "async", "off") else "async"
# Доп. вызов ИИ: привести названия блюд к каноничным (карбонара, а не «макароны с беконом»)
_oct = os.getenv("OPENAI_CANONICALIZE_TITLES", "on").strip().lower()
OPENAI_CANONICALIZE_TITLES = _oct not in ("0", "false", "no", "off")
# Таймаут HTTP для OpenAI (сек.): DALL·E и длинные ответы
OPENAI_HTTP_TIMEOUT_SEC = max(1.0, _env_float("OPENAI_HTTP_TIMEOUT_SEC", 180.0))

# Бесплатный fallback для канонизации названий блюд через Wikipedia API (без ключа).
_fta = os.getenv("FREE_TITLE_API_ENABLED", "on").strip().lower()
FREE_TITLE_API_ENABLED = _fta not in ("0", "false", "no", "off")
FREE_TITLE_API_TIMEOUT_SEC = max(0.5, _env_float("FREE_TITLE_API_TIMEOUT_SEC", 4.0))

# Раздел «кухни мира» — только генерация через OpenAI (база для подбора не используется).
CUISINES_AI_MODE = "always"


def cuisine_ai_enabled() -> bool:
    """Можно вызывать ИИ для кухонного потока (нужен ключ)."""
    return bool(OPENAI_API_KEY)
