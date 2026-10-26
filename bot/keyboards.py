"""Кнопки."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

BTN_ADD = "➕ Добавить"
BTN_ARCHIVE = "🗂 Архив"
BTN_SEARCH = "🔎 Поиск"
BTN_SUBJECTS = "📚 Предметы"
BTN_TEACHERS = "👨‍🏫 Преподаватели"
BTN_PDF = "📄 PDF из текста"
BTN_BACKUP = "💾 Бэкап"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_ARCHIVE)],
            [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_SUBJECTS)],
            [KeyboardButton(text=BTN_TEACHERS), KeyboardButton(text=BTN_PDF)],
            [KeyboardButton(text=BTN_BACKUP)],
        ],
        resize_keyboard=True,
    )


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_kb(m: dict) -> InlineKeyboardMarkup:
    """Кнопки под карточкой материала."""
    star = "⭐ Важно ✓" if m["important"] else "☆ Важно к экзамену"
    return kb(
        [
            [btn(star, f"mat:imp:{m['id']}"), btn("🏷 Теги", f"mat:tags:{m['id']}")],
            [
                btn("🗑 Удалить", f"mat:del:{m['id']}"),
                btn("🔙 К списку", f"arcl:{m['subject_id']}:all:0"),
            ],
        ]
    )


def date_kb(prefix: str) -> InlineKeyboardMarkup:
    return kb(
        [
            [btn("Сегодня", f"{prefix}:today"), btn("Вчера", f"{prefix}:yest")],
            [btn("📅 Другая дата", f"{prefix}:other")],
            [btn("❌ Отмена", "add:cancel")],
        ]
    )
