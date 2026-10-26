"""Приём материалов: фото, PDF, документы, текст -> предмет -> дата -> сохранение."""
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from datetime import timedelta

from .. import db
from ..keyboards import btn, card_kb, date_kb, kb
from ..utils import esc, fmt_date, parse_date, today

router = Router()


class Add(StatesGroup):
    collecting = State()
    choosing_subject = State()
    new_subject = State()
    choosing_date = State()
    entering_date = State()


def collect_kb():
    return kb([[btn("✅ Готово", "add:done")], [btn("❌ Отмена", "add:cancel")]])


# ---------- Старт ----------
async def start_add(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Add.collecting)
    await state.update_data(items=[], last_group=None)
    await message.answer(
        "Присылай фото, PDF, документы или текст (можно несколько сразу).\n"
        "Когда всё отправишь, нажми «✅ Готово».",
        reply_markup=collect_kb(),
    )


@router.callback_query(F.data == "add:cancel")
async def add_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer("Отменено")
    await cb.message.answer("Отменено.")


# ---------- Приём содержимого ----------
async def _append(message: Message, state: FSMContext, item: dict) -> None:
    data = await state.get_data()
    items = list(data.get("items", []))
    items.append(item)
    gid = message.media_group_id
    quiet = bool(gid) and data.get("last_group") == gid
    await state.set_state(Add.collecting)
    await state.update_data(items=items, last_group=gid)
    if not quiet:
        await message.answer(
            "📥 Принято. Присылай ещё или нажми «✅ Готово».", reply_markup=collect_kb()
        )


@router.message(StateFilter(None, Add.collecting), F.photo)
async def got_photo(message: Message, state: FSMContext) -> None:
    p = message.photo[-1]
    await _append(
        message,
        state,
        {
            "kind": "photo",
            "file_id": p.file_id,
            "file_unique_id": p.file_unique_id,
            "file_name": None,
            "text": None,
            "caption": message.caption,
        },
    )


@router.message(StateFilter(None, Add.collecting), F.document)
async def got_document(message: Message, state: FSMContext) -> None:
    d = message.document
    kind = "pdf" if d.mime_type == "application/pdf" else "document"
    await _append(
        message,
        state,
        {
            "kind": kind,
            "file_id": d.file_id,
            "file_unique_id": d.file_unique_id,
            "file_name": d.file_name,
            "text": None,
            "caption": message.caption,
        },
    )


@router.message(Add.collecting, F.text, ~F.text.startswith("/"))
async def got_text(message: Message, state: FSMContext) -> None:
    await _append(
        message,
        state,
        {
            "kind": "text",
            "file_id": None,
            "file_unique_id": None,
            "file_name": None,
            "text": message.text,
            "caption": None,
        },
    )


# ---------- Выбор предмета ----------
async def ask_subject(message: Message, state: FSMContext) -> None:
    subjects = await db.list_subjects()
    if not subjects:
        await state.set_state(Add.new_subject)
        await message.answer("Предметов пока нет. Напиши название первого предмета:")
        return
    rows = [[btn(s["name"], f"addsub:{s['id']}")] for s in subjects]
    rows.append([btn("➕ Новый предмет", "addsub:new")])
    rows.append([btn("❌ Отмена", "add:cancel")])
    await state.set_state(Add.choosing_subject)
    await message.answer("К какому предмету отнести?", reply_markup=kb(rows))


@router.callback_query(F.data == "add:done", Add.collecting)
async def add_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("items"):
        await cb.answer("Пока ничего не прислано", show_alert=True)
        return
    await cb.answer()
    await ask_subject(cb.message, state)


@router.callback_query(F.data.startswith("addsub:"), Add.choosing_subject)
async def subject_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    arg = cb.data.split(":")[1]
    await cb.answer()
    if arg == "new":
        await state.set_state(Add.new_subject)
        await cb.message.answer("Напиши название нового предмета:")
        return
    await state.update_data(subject_id=int(arg))
    await _after_subject(cb.message, state)


@router.message(Add.new_subject, F.text, ~F.text.startswith("/"))
async def new_subject_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if not 1 <= len(name) <= 60:
        await message.answer("Название должно быть от 1 до 60 символов. Попробуй ещё раз:")
        return
    sid, _ = await db.add_subject(name)
    await state.update_data(subject_id=sid)
    await _after_subject(message, state)


async def _after_subject(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("date"):  # дата уже известна (например, после «PDF из текста»)
        await _save(message, state, data["date"])
        return
    await state.set_state(Add.choosing_date)
    await message.answer("На какую дату записать?", reply_markup=date_kb("adddate"))


# ---------- Дата ----------
@router.callback_query(F.data.startswith("adddate:"), Add.choosing_date)
async def date_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    arg = cb.data.split(":")[1]
    await cb.answer()
    if arg == "today":
        await _save(cb.message, state, today().isoformat())
    elif arg == "yest":
        await _save(cb.message, state, (today() - timedelta(days=1)).isoformat())
    else:
        await state.set_state(Add.entering_date)
        await cb.message.answer("Напиши дату в формате ДД.ММ.ГГГГ (например, 14.03.2026):")


@router.message(Add.entering_date, F.text, ~F.text.startswith("/"))
async def date_typed(message: Message, state: FSMContext) -> None:
    d = parse_date(message.text)
    if not d:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ, например 14.03.2026")
        return
    await _save(message, state, d.isoformat())


# ---------- Сохранение ----------
async def _save(message: Message, state: FSMContext, date_iso: str) -> None:
    data = await state.get_data()
    sid = data["subject_id"]
    ids = []
    for it in data["items"]:
        ids.append(
            await db.add_material(
                subject_id=sid,
                kind=it["kind"],
                date=date_iso,
                file_id=it.get("file_id"),
                file_unique_id=it.get("file_unique_id"),
                file_name=it.get("file_name"),
                text=it.get("text"),
                caption=it.get("caption"),
            )
        )
    subj = await db.get_subject(sid)
    await state.clear()
    head = f"✅ Сохранено: {len(ids)} → <b>{esc(subj['name'])}</b>, {fmt_date(date_iso)}"
    if len(ids) == 1:
        m = await db.get_material(ids[0])
        await message.answer(head, reply_markup=card_kb(m))
    else:
        await message.answer(
            head, reply_markup=kb([[btn("🗂 Открыть архив предмета", f"arcl:{sid}:all:0")]])
        )
