"""PDF из текста с датой (с кириллицей) и предложение сохранить в архив."""
import asyncio
from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram import Bot

from .. import pdf_tools
from ..keyboards import date_kb
from ..utils import fmt_date, parse_date, safe_filename, today
from .materials import Add, ask_subject

router = Router()


class PdfStates(StatesGroup):
    text = State()
    date = State()
    date_typed = State()


async def start_pdf(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PdfStates.text)
    await message.answer(
        "📄 Пришли текст для PDF (или файл .txt).\n"
        "Если в тексте несколько строк, первая станет заголовком."
    )


@router.message(PdfStates.text, F.text, ~F.text.startswith("/"))
async def got_text(message: Message, state: FSMContext) -> None:
    await state.update_data(pdf_text=message.text)
    await state.set_state(PdfStates.date)
    await message.answer("Какую дату поставить в PDF?", reply_markup=date_kb("pdate"))


@router.message(PdfStates.text, F.document)
async def got_txt_file(message: Message, state: FSMContext, bot: Bot) -> None:
    d = message.document
    if not (d.file_name or "").lower().endswith(".txt") or (d.file_size or 0) > 1_000_000:
        await message.answer("Нужен текстовый файл .txt размером до 1 МБ.")
        return
    buf = await bot.download(d.file_id)
    raw = buf.read()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = ""
    if not text.strip():
        await message.answer("Не смог прочитать файл. Пришли текст сообщением.")
        return
    await state.update_data(pdf_text=text)
    await state.set_state(PdfStates.date)
    await message.answer("Какую дату поставить в PDF?", reply_markup=date_kb("pdate"))


@router.callback_query(F.data.startswith("pdate:"), PdfStates.date)
async def date_chosen(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    arg = cb.data.split(":")[1]
    await cb.answer()
    if arg == "today":
        await _make_pdf(cb.message, state, today().isoformat())
    elif arg == "yest":
        await _make_pdf(cb.message, state, (today() - timedelta(days=1)).isoformat())
    else:
        await state.set_state(PdfStates.date_typed)
        await cb.message.answer("Напиши дату в формате ДД.ММ.ГГГГ:")


@router.message(PdfStates.date_typed, F.text, ~F.text.startswith("/"))
async def date_typed(message: Message, state: FSMContext) -> None:
    d = parse_date(message.text)
    if not d:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ")
        return
    await _make_pdf(message, state, d.isoformat())


def _split_title(text: str) -> tuple[str, str]:
    lines = text.strip().splitlines()
    if len(lines) > 1 and 0 < len(lines[0].strip()) <= 80:
        return lines[0].strip(), "\n".join(lines[1:]).strip()
    return "Конспект", text.strip()


async def _make_pdf(message: Message, state: FSMContext, date_iso: str) -> None:
    data = await state.get_data()
    text = data["pdf_text"]
    title, body = _split_title(text)
    pdf = await asyncio.to_thread(
        pdf_tools.text_pdf_bytes, title, fmt_date(date_iso), body
    )
    filename = f"{safe_filename(title)}_{date_iso}.pdf"
    sent = await message.answer_document(
        BufferedInputFile(pdf, filename=filename),
        caption=f"📄 {title} · {fmt_date(date_iso)}",
    )
    # Предлагаем сохранить в архив: подставляем готовый файл и дату в общий сценарий
    await state.clear()
    await state.set_state(Add.choosing_subject)
    await state.update_data(
        date=date_iso,
        items=[
            {
                "kind": "pdf",
                "file_id": sent.document.file_id,
                "file_unique_id": sent.document.file_unique_id,
                "file_name": filename,
                "text": text,
                "caption": title,
            }
        ],
    )
    await message.answer("Сохранить этот PDF в архив? Выбери предмет (или отмена):")
    await ask_subject(message, state)
