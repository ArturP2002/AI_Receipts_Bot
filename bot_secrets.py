
import os
from dotenv import find_dotenv, load_dotenv

env_path = find_dotenv()
if env_path:
    load_dotenv(env_path)
else:
    load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_USER_IDS", "").split(",")
    if x.strip().isdigit()
]

# Публичный https:// URL сервера админ mini app (без слэша в конце), например https://abc.ngrok-free.app
ADMIN_WEBAPP_PUBLIC_URL = (os.getenv("ADMIN_WEBAPP_PUBLIC_URL") or "").strip().rstrip("/")
ADMIN_WEBAPP_HOST = (os.getenv("ADMIN_WEBAPP_HOST") or "0.0.0.0").strip() or "0.0.0.0"
ADMIN_WEBAPP_PORT = int(os.getenv("ADMIN_WEBAPP_PORT", "8765") or "8765")


def validate_config() -> None:
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if missing:
        raise RuntimeError(
            "Отсутствуют переменные окружения: " + ", ".join(missing)
        )
