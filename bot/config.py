"""Настройки бота. Всё берётся из переменных окружения (или из файла .env)."""
import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # на сервере переменные приходят из Docker
    pass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_id: int
    db_path: str
    timezone: str
    backup_hour: int
    port: int
    base_url: str  # публичный адрес сервиса; если задан, бот работает через webhook
    secret: str


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. Посмотри файл .env.example"
        )
    return value


@lru_cache
def get_settings() -> Settings:
    try:
        owner_id = int(_require("OWNER_ID"))
    except ValueError:
        raise RuntimeError("OWNER_ID должен быть числом (твой Telegram ID)")
    try:
        backup_hour = int(os.getenv("BACKUP_HOUR", "3"))
    except ValueError:
        raise RuntimeError("BACKUP_HOUR должен быть числом от 0 до 23")
    if not 0 <= backup_hour <= 23:
        raise RuntimeError("BACKUP_HOUR должен быть числом от 0 до 23")
    token = _require("BOT_TOKEN")
    base_url = (
        os.getenv("WEBHOOK_BASE_URL", "").strip()
        or os.getenv("RENDER_EXTERNAL_URL", "").strip()
    ).rstrip("/")
    try:
        port = int(os.getenv("PORT", "10000"))
    except ValueError:
        port = 10000
    return Settings(
        bot_token=token,
        owner_id=owner_id,
        db_path=os.getenv("DB_PATH", "data/bot.db").strip(),
        timezone=os.getenv("TIMEZONE", "Europe/Warsaw").strip(),
        backup_hour=backup_hour,
        port=port,
        base_url=base_url,
        secret=hashlib.sha256((token + ":secret").encode()).hexdigest()[:48],
    )
