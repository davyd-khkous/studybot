"""Предметы: список, добавление, переименование, удаление."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import db
from ..keyboards import btn, kb
from ..utils import esc, safe_edit

router = Router()


class SubjectStates(StatesGroup):
    adding = State()
    renaming = State()


async def _list_view():
    subjects = await db.list_subjects()
    rows = [
        [btn(f"{s['name']} ({s['cnt']})", f"subj:open:{s['id']}")] for s in subjects
    ]
    rows.append([btn("➕ Добавить предмет", "subj:add")])
    text = "📚 <b>Предметы</b>" if subjects else "📚 Предметов пока нет. Добавь первый:"
    return text, kb(rows)


async def show_subjects(message: Message) -> None:
    text, markup = await _list_view()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "subj:list")
async def cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    text, markup = await _list_view()
    await safe_edit(cb, text, markup)


@router.callback_query(F.data.startswith("subj:open:"))
async def cb_open(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":")[2])
    s = await db.get_subject(sid)
    await cb.answer()
    if not s:
        await safe_edit(cb, "Предмет не найден.")
        return
    text = (
        f"📘 <b>{esc(s['name'])}</b>\n"
        f"Материалов: {s['cnt']}, важных к экзамену: {s['imp']}"
    )
    markup = kb(
        [
            [btn("🗂 Материалы", f"arcl:{sid}:all:0")],
            [btn("📤 Все конспекты одним PDF", f"exp:{sid}")],
            [btn("✏️ Переименовать", f"subj:ren:{sid}"), btn("🗑 Удалить", f"subj:del:{sid}")],
            [btn("🔙 К предметам", "subj:list")],
        ]
    )
    await safe_edit(cb, text, markup)


# ---------- Добавление ----------
@router.callback_query(F.data == "subj:add")
async def cb_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SubjectStates.adding)
    await cb.answer()
    await cb.message.answer("Напиши название предмета:")


@router.message(SubjectStates.adding, F.text, ~F.text.startswith("/"))
async def adding_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if not 1 <= len(name) <= 60:
        await message.answer("Название должно быть от 1 до 60 символов. Ещё раз:")
        return
    _, created = await db.add_subject(name)
    await state.clear()
    await message.answer("✅ Добавлено." if created else "Такой предмет уже есть.")
    await show_subjects(message)


# ---------- Переименование ----------
@router.callback_query(F.data.startswith("subj:ren:"))
async def cb_rename(cb: CallbackQuery, state: FSMContext) -> None:
    sid = int(cb.data.split(":")[2])
    await state.clear()
    await state.set_state(SubjectStates.renaming)
    await state.update_data(subject_id=sid)
    await cb.answer()
    await cb.message.answer("Напиши новое название:")


@router.message(SubjectStates.renaming, F.text, ~F.text.startswith("/"))
async def renaming_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = " ".join(message.text.split())
    if not 1 <= len(name) <= 60:
        await message.answer("Название должно быть от 1 до 60 символов. Ещё раз:")
        return
    ok = await db.rename_subject(data["subject_id"], name)
    if not ok:
        await message.answer("Предмет с таким названием уже есть. Придумай другое:")
        return
    await state.clear()
    await message.answer("✅ Переименовано.")
    await show_subjects(message)


# ---------- Удаление ----------
@router.callback_query(F.data.startswith("subj:del:"))
async def cb_delete(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":")[2])
    s = await db.get_subject(sid)
    await cb.answer()
    if not s:
        return
    await safe_edit(
        cb,
        f"Удалить предмет <b>{esc(s['name'])}</b> вместе со всеми материалами ({s['cnt']})?\n"
        "Это нельзя отменить.",
        kb(
            [
                [btn("🗑 Да, удалить", f"subj:delok:{sid}")],
                [btn("Отмена", f"subj:open:{sid}")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("subj:delok:"))
async def cb_delete_ok(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":")[2])
    await db.delete_subject(sid)
    await cb.answer("Удалено")
    text, markup = await _list_view()
    await safe_edit(cb, text, markup)
