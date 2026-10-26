"""Запасные обработчики: подключаются последними."""
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..keyboards import main_menu

router = Router()


@router.callback_query()
async def stale_button(cb: CallbackQuery) -> None:
    await cb.answer(
        "Эта кнопка устарела (бот перезапускался). Открой нужный раздел заново.",
        show_alert=True,
    )


@router.message()
async def unknown(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Не понял. Выбери действие в меню или пришли фото/файл, чтобы сохранить.",
        reply_markup=main_menu(),
    )
