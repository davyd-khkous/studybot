"""Главное меню и команды. Подключается первым, чтобы кнопки меню работали в любом состоянии."""
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from .. import backup
from ..config import get_settings
from ..keyboards import (
    BTN_ADD,
    BTN_ARCHIVE,
    BTN_BACKUP,
    BTN_PDF,
    BTN_SEARCH,
    BTN_SUBJECTS,
    BTN_TEACHERS,
    main_menu,
)
from . import archive, materials, pdf_note, subjects, teachers

router = Router()

WELCOME = (
    "👋 Привет! Это твой учебный бот.\n\n"
    "• Присылай фото, PDF, документы и текст: я сохраню их по предметам и датам.\n"
    "• «🗂 Архив» и «🔎 Поиск» помогут быстро найти нужное.\n"
    "• «📄 PDF из текста» сделает аккуратный PDF.\n\n"
    "Выбирай действие в меню внизу. Отменить любое действие: /cancel"
)


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())


@router.message(F.text == BTN_ADD)
@router.message(Command("add"))
async def menu_add(message: Message, state: FSMContext) -> None:
    await materials.start_add(message, state)


@router.message(F.text == BTN_ARCHIVE)
async def menu_archive(message: Message, state: FSMContext) -> None:
    await state.clear()
    await archive.ask_subject_for_archive(message)


@router.message(F.text == BTN_SEARCH)
async def menu_search(message: Message, state: FSMContext) -> None:
    await archive.start_search(message, state)


@router.message(F.text == BTN_SUBJECTS)
async def menu_subjects(message: Message, state: FSMContext) -> None:
    await state.clear()
    await subjects.show_subjects(message)


@router.message(F.text == BTN_TEACHERS)
async def menu_teachers(message: Message, state: FSMContext) -> None:
    await state.clear()
    await teachers.show_teachers(message)


@router.message(F.text == BTN_PDF)
async def menu_pdf(message: Message, state: FSMContext) -> None:
    await pdf_note.start_pdf(message, state)


@router.message(F.text == BTN_BACKUP)
@router.message(Command("backup"))
async def menu_backup(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await message.answer("⏳ Делаю бэкап…")
    result = await backup.make_backup(bot, get_settings(), force=True)
    if result != "ok":
        await message.answer("⚠️ Не получилось сделать бэкап. Подробности в логах сервера.")
