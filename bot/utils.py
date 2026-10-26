"""Мелкие помощники: даты, экранирование, безопасное редактирование."""
import html
import re
from datetime import date, datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from .config import get_settings

KIND_ICONS = {"photo": "🖼", "pdf": "📕", "document": "📎", "text": "📝"}
KIND_NAMES = {"photo": "фото", "pdf": "PDF", "document": "файл", "text": "текст"}


def esc(value) -> str:
    """Экранирует текст пользователя для HTML-разметки Telegram."""
    return html.escape(str(value or ""), quote=False)


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def parse_date(text: str) -> Optional[date]:
    text = (text or "").strip().replace("/", ".").replace(",", ".")
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    try:
        d = datetime.strptime(text + f".{today().year}", "%d.%m.%Y").date()
        return d
    except ValueError:
        return None


def parse_date_range(text: str) -> Optional[Tuple[date, date]]:
    parts = re.split(r"\s*[-–—]\s*", (text or "").strip())
    if len(parts) == 1:
        d = parse_date(parts[0])
        return (d, d) if d else None
    if len(parts) == 2:
        a, b = parse_date(parts[0]), parse_date(parts[1])
        if a and b:
            return (a, b) if a <= b else (b, a)
    return None


def short(text: str, n: int = 40) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "").strip(" ._")
    return name[:60] or "file"


async def safe_edit(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    """Редактирует сообщение с кнопкой; если нельзя — шлёт новое."""
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await cb.message.answer(text, reply_markup=reply_markup)
