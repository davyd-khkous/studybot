"""Карточки преподавателей."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import db
from ..keyboards import btn, kb
from ..utils import esc, safe_edit

router = Router()

FIELDS = [
    ("name", "ФИО"),
    ("contacts", "Контакты (почта, телефон, мессенджер)"),
    ("consultations", "Консультации (когда и где)"),
    ("how_accepts", "Как принимает (устно/письменно, требования)"),
    ("notes", "Заметки"),
]
LABELS = dict(FIELDS)


class TeacherStates(StatesGroup):
    adding = State()
    editing = State()


async def _list_view():
    teachers = await db.list_teachers()
    rows = [[btn(t["name"], f"t:open:{t['id']}")] for t in teachers]
    rows.append([btn("➕ Добавить преподавателя", "t:add")])
    text = "👨‍🏫 <b>Преподаватели</b>" if teachers else "👨‍🏫 Преподавателей пока нет."
    return text, kb(rows)


async def show_teachers(message: Message) -> None:
    text, markup = await _list_view()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "t:list")
async def cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer()
    text, markup = await _list_view()
    await safe_edit(cb, text, markup)


def _card(t: dict) -> str:
    def v(key):
        return esc(t[key]) if t[key] else "—"

    return (
        f"👨‍🏫 <b>{esc(t['name'])}</b>\n\n"
        f"📞 <b>Контакты:</b> {v('contacts')}\n"
        f"🕒 <b>Консультации:</b> {v('consultations')}\n"
        f"📝 <b>Как принимает:</b> {v('how_accepts')}\n"
        f"💬 <b>Заметки:</b> {v('notes')}"
    )


def _card_kb(tid: int):
    return kb(
        [
            [btn("✏️ ФИО", f"t:edit:{tid}:name"), btn("✏️ Контакты", f"t:edit:{tid}:contacts")],
            [btn("✏️ Консультации", f"t:edit:{tid}:consultations")],
            [btn("✏️ Как принимает", f"t:edit:{tid}:how_accepts")],
            [btn("✏️ Заметки", f"t:edit:{tid}:notes")],
            [btn("🗑 Удалить", f"t:del:{tid}"), btn("🔙 К списку", "t:list")],
        ]
    )


@router.callback_query(F.data.startswith("t:open:"))
async def cb_open(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = int(cb.data.split(":")[2])
    t = await db.get_teacher(tid)
    await cb.answer()
    if not t:
        await safe_edit(cb, "Не найден.")
        return
    await safe_edit(cb, _card(t), _card_kb(tid))


# ---------- Добавление по шагам ----------
def _skip_kb(step: int):
    if step == 0:
        return kb([[btn("❌ Отмена", "t:list")]])
    return kb([[btn("⏭ Пропустить", "t:skip")], [btn("❌ Отмена", "t:list")]])


async def _ask_step(message: Message, step: int) -> None:
    await message.answer(f"{LABELS[FIELDS[step][0]]}:", reply_markup=_skip_kb(step))


@router.callback_query(F.data == "t:add")
async def cb_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TeacherStates.adding)
    await state.update_data(step=0, values={})
    await cb.answer()
    await _ask_step(cb.message, 0)


async def _advance(message: Message, state: FSMContext, value: str) -> None:
    data = await state.get_data()
    step = data["step"]
    values = dict(data["values"])
    values[FIELDS[step][0]] = value
    step += 1
    if step < len(FIELDS):
        await state.update_data(step=step, values=values)
        await _ask_step(message, step)
        return
    tid = await db.add_teacher(**values)
    await state.clear()
    t = await db.get_teacher(tid)
    await message.answer("✅ Карточка создана.")
    await message.answer(_card(t), reply_markup=_card_kb(tid))


@router.message(TeacherStates.adding, F.text, ~F.text.startswith("/"))
async def adding_text(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    data = await state.get_data()
    if data["step"] == 0 and not value:
        await message.answer("ФИО не может быть пустым.")
        return
    await _advance(message, state, value)


@router.callback_query(F.data == "t:skip", TeacherStates.adding)
async def cb_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await _advance(cb.message, state, "")


# ---------- Редактирование ----------
@router.callback_query(F.data.startswith("t:edit:"))
async def cb_edit(cb: CallbackQuery, state: FSMContext) -> None:
    _, _, tid, field = cb.data.split(":")
    if field not in LABELS:
        await cb.answer()
        return
    await state.clear()
    await state.set_state(TeacherStates.editing)
    await state.update_data(teacher_id=int(tid), field=field)
    await cb.answer()
    extra = "" if field == "name" else "\nЧтобы очистить поле, отправь «-»."
    await cb.message.answer(f"Новое значение. {LABELS[field]}:{extra}")


@router.message(TeacherStates.editing, F.text, ~F.text.startswith("/"))
async def edit_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    value = message.text.strip()
    if data["field"] != "name" and value == "-":
        value = ""
    if data["field"] == "name" and not value:
        await message.answer("ФИО не может быть пустым.")
        return
    await db.update_teacher(data["teacher_id"], data["field"], value)
    await state.clear()
    t = await db.get_teacher(data["teacher_id"])
    await message.answer("✅ Обновлено.")
    await message.answer(_card(t), reply_markup=_card_kb(t["id"]))


# ---------- Удаление ----------
@router.callback_query(F.data.startswith("t:del:"))
async def cb_delete(cb: CallbackQuery) -> None:
    tid = int(cb.data.split(":")[2])
    t = await db.get_teacher(tid)
    await cb.answer()
    if not t:
        return
    await safe_edit(
        cb,
        f"Удалить карточку <b>{esc(t['name'])}</b>?",
        kb([[btn("🗑 Да", f"t:delok:{tid}")], [btn("Отмена", f"t:open:{tid}")]]),
    )


@router.callback_query(F.data.startswith("t:delok:"))
async def cb_delete_ok(cb: CallbackQuery) -> None:
    await db.delete_teacher(int(cb.data.split(":")[2]))
    await cb.answer("Удалено")
    text, markup = await _list_view()
    await safe_edit(cb, text, markup)
