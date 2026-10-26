"""Теги и пометка «важно к экзамену»."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import db
from ..keyboards import btn, card_kb, kb
from ..utils import esc, safe_edit

router = Router()


class TagStates(StatesGroup):
    adding = State()


@router.callback_query(F.data.startswith("mat:imp:"))
async def cb_toggle_important(cb: CallbackQuery) -> None:
    mid = int(cb.data.split(":")[2])
    await db.toggle_important(mid)
    m = await db.get_material(mid)
    if not m:
        await cb.answer("Материал не найден", show_alert=True)
        return
    await cb.answer("⭐ Отмечено важным" if m["important"] else "Пометка снята")
    await cb.message.edit_reply_markup(reply_markup=card_kb(m))


async def _tags_view(mid: int):
    tags = await db.material_tags(mid)
    rows = [[btn(f"❌ #{t['name']}", f"tagdel:{mid}:{t['id']}")] for t in tags]
    rows.append([btn("✅ Готово", f"tagdone:{mid}")])
    cur = " ".join(f"#{esc(t['name'])}" for t in tags) or "пока нет"
    text = (
        f"🏷 <b>Теги:</b> {cur}\n\n"
        "Напиши новые теги через запятую (например: билет 5, формулы).\n"
        "Чтобы убрать тег, нажми на него."
    )
    return text, kb(rows)


@router.callback_query(F.data.startswith("mat:tags:"))
async def cb_open_tags(cb: CallbackQuery, state: FSMContext) -> None:
    mid = int(cb.data.split(":")[2])
    await state.clear()
    await state.set_state(TagStates.adding)
    await state.update_data(material_id=mid)
    await cb.answer()
    text, markup = await _tags_view(mid)
    await cb.message.answer(text, reply_markup=markup)


@router.message(TagStates.adding, F.text, ~F.text.startswith("/"))
async def tags_typed(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    mid = data["material_id"]
    names = [p for p in message.text.replace(";", ",").replace("\n", ",").split(",")]
    await db.add_tags(mid, names)
    text, markup = await _tags_view(mid)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("tagdel:"))
async def cb_tag_delete(cb: CallbackQuery) -> None:
    _, mid, tid = cb.data.split(":")
    await db.remove_tag(int(mid), int(tid))
    await cb.answer("Тег убран")
    text, markup = await _tags_view(int(mid))
    await safe_edit(cb, text, markup)


@router.callback_query(F.data.startswith("tagdone:"))
async def cb_tags_done(cb: CallbackQuery, state: FSMContext) -> None:
    mid = int(cb.data.split(":")[1])
    await state.clear()
    await cb.answer("Сохранено")
    await safe_edit(
        cb,
        "🏷 Теги сохранены.",
        kb([[btn("📂 Открыть материал", f"mat:open:{mid}")]]),
    )
