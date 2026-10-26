"""Архив по предметам и датам, карточки материалов, поиск."""
import math

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import db
from ..keyboards import btn, card_kb, kb
from ..utils import (
    KIND_ICONS,
    esc,
    fmt_date,
    parse_date_range,
    safe_edit,
    short,
)

router = Router()
PAGE = 8


class ArchiveStates(StatesGroup):
    date = State()


class SearchState(StatesGroup):
    waiting = State()


def _label(m: dict, with_subject: bool = False) -> str:
    star = "⭐" if m["important"] else ""
    preview = m.get("text") or m.get("caption") or m.get("file_name") or ""
    prefix = f"{m['subject_name']} · " if with_subject and m.get("subject_name") else ""
    d = fmt_date(m["date"])[:5]
    return short(f"{star}{KIND_ICONS.get(m['kind'], '📎')} {prefix}{d} {preview}", 60)


def _flt_title(flt: str, tag_name: str = "") -> str:
    if flt == "all":
        return "все материалы"
    if flt == "imp":
        return "⭐ важное к экзамену"
    if flt.startswith("t"):
        return f"тег #{tag_name}"
    if flt.startswith("d"):
        a, b = flt[1:].split("_")
        fa = f"{a[6:]}.{a[4:6]}.{a[:4]}"
        fb = f"{b[6:]}.{b[4:6]}.{b[:4]}"
        return f"даты {fa}" if a == b else f"даты {fa} - {fb}"
    return ""


# ---------- Выбор предмета ----------
async def ask_subject_for_archive(message: Message) -> None:
    subjects = await db.list_subjects()
    if not subjects:
        await message.answer("Сначала добавь предмет в разделе «📚 Предметы».")
        return
    rows = [[btn(f"{s['name']} ({s['cnt']})", f"arcsub:{s['id']}")] for s in subjects]
    await message.answer("🗂 Выбери предмет:", reply_markup=kb(rows))


@router.callback_query(F.data.startswith("arcsub:"))
async def cb_subject_menu(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":")[1])
    s = await db.get_subject(sid)
    await cb.answer()
    if not s:
        await safe_edit(cb, "Предмет не найден.")
        return
    markup = kb(
        [
            [btn("📋 Все", f"arcl:{sid}:all:0"), btn("⭐ Важное", f"arcl:{sid}:imp:0")],
            [btn("🏷 По тегам", f"arcm:tags:{sid}"), btn("📅 По датам", f"arcm:date:{sid}")],
            [btn("📤 Всё одним PDF", f"exp:{sid}")],
        ]
    )
    await safe_edit(
        cb,
        f"📘 <b>{esc(s['name'])}</b>\nМатериалов: {s['cnt']}, важных: {s['imp']}",
        markup,
    )


# ---------- Список ----------
async def _render_list(sid: int, flt: str, page: int):
    subj = await db.get_subject(sid)
    if not subj:
        return "Предмет не найден.", None
    tag_name = ""
    if flt.startswith("t") and flt[1:].isdigit():
        for t in await db.tags_for_subject(sid):
            if t["id"] == int(flt[1:]):
                tag_name = t["name"]
    items = await db.list_materials(sid, flt)
    pages = max(1, math.ceil(len(items) / PAGE))
    page = min(max(page, 0), pages - 1)
    chunk = items[page * PAGE : (page + 1) * PAGE]
    rows = [[btn(_label(m), f"mat:open:{m['id']}")] for m in chunk]
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(btn("◀️", f"arcl:{sid}:{flt}:{page - 1}"))
        nav.append(btn(f"{page + 1}/{pages}", "noop"))
        if page < pages - 1:
            nav.append(btn("▶️", f"arcl:{sid}:{flt}:{page + 1}"))
        rows.append(nav)
    rows.append([btn("🔙 К предмету", f"arcsub:{sid}")])
    text = f"📘 <b>{esc(subj['name'])}</b> · {esc(_flt_title(flt, tag_name))}\nНайдено: {len(items)}"
    if not items:
        text += "\nПока пусто."
    return text, kb(rows)


@router.callback_query(F.data.startswith("arcl:"))
async def cb_list(cb: CallbackQuery) -> None:
    _, sid, flt, page = cb.data.split(":")
    await cb.answer()
    text, markup = await _render_list(int(sid), flt, int(page))
    await safe_edit(cb, text, markup)


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data.startswith("arcm:tags:"))
async def cb_tags_menu(cb: CallbackQuery) -> None:
    sid = int(cb.data.split(":")[2])
    tags = await db.tags_for_subject(sid)
    if not tags:
        await cb.answer("В этом предмете пока нет тегов", show_alert=True)
        return
    await cb.answer()
    rows = [[btn(f"#{t['name']} ({t['cnt']})", f"arcl:{sid}:t{t['id']}:0")] for t in tags]
    rows.append([btn("🔙 Назад", f"arcsub:{sid}")])
    await safe_edit(cb, "🏷 Выбери тег:", kb(rows))


@router.callback_query(F.data.startswith("arcm:date:"))
async def cb_date_menu(cb: CallbackQuery, state: FSMContext) -> None:
    sid = int(cb.data.split(":")[2])
    await state.clear()
    await state.set_state(ArchiveStates.date)
    await state.update_data(subject_id=sid)
    await cb.answer()
    await cb.message.answer(
        "📅 Напиши дату (ДД.ММ.ГГГГ) или период (ДД.ММ.ГГГГ-ДД.ММ.ГГГГ):"
    )


@router.message(ArchiveStates.date, F.text, ~F.text.startswith("/"))
async def date_typed(message: Message, state: FSMContext) -> None:
    rng = parse_date_range(message.text)
    if not rng:
        await message.answer(
            "Не понял. Пример: 14.03.2026 или 01.03.2026-31.03.2026"
        )
        return
    data = await state.get_data()
    await state.clear()
    a, b = rng
    flt = f"d{a:%Y%m%d}_{b:%Y%m%d}"
    text, markup = await _render_list(data["subject_id"], flt, 0)
    await message.answer(text, reply_markup=markup)


# ---------- Карточка материала ----------
def _card_text(m: dict) -> str:
    parts = [f"{KIND_ICONS.get(m['kind'], '📎')} <b>{esc(m['subject_name'])}</b> · {fmt_date(m['date'])}"]
    if m["important"]:
        parts.append("⭐ важно к экзамену")
    if m.get("tags_str"):
        tags = " ".join("#" + t.strip().replace(" ", "_") for t in m["tags_str"].split(","))
        parts.append(esc(tags))
    if m.get("file_name"):
        parts.append(f"📄 {esc(m['file_name'])}")
    if m["kind"] != "text" and m.get("caption"):
        parts.append(esc(short(m["caption"], 500)))
    return "\n".join(parts)


@router.callback_query(F.data.startswith("mat:open:"))
async def cb_open_material(cb: CallbackQuery, bot: Bot) -> None:
    mid = int(cb.data.split(":")[2])
    m = await db.get_material(mid)
    await cb.answer()
    if not m:
        await cb.message.answer("Материал не найден (возможно, удалён).")
        return
    chat_id = cb.message.chat.id
    markup = card_kb(m)
    head = _card_text(m)
    if m["kind"] == "text":
        body = m["text"] or ""
        limit = 3500
        chunks = [body[i : i + limit] for i in range(0, len(body), limit)] or [""]
        await bot.send_message(chat_id, head + "\n\n" + esc(chunks[0]),
                               reply_markup=markup if len(chunks) == 1 else None)
        for i, ch in enumerate(chunks[1:], start=1):
            last = i == len(chunks) - 1
            await bot.send_message(chat_id, esc(ch), reply_markup=markup if last else None)
    elif m["kind"] == "photo":
        await bot.send_photo(chat_id, m["file_id"], caption=head, reply_markup=markup)
    else:
        await bot.send_document(chat_id, m["file_id"], caption=head, reply_markup=markup)


# ---------- Удаление материала ----------
@router.callback_query(F.data.startswith("mat:del:"))
async def cb_delete(cb: CallbackQuery) -> None:
    mid = int(cb.data.split(":")[2])
    await cb.answer()
    await cb.message.edit_reply_markup(
        reply_markup=kb(
            [
                [btn("🗑 Да, удалить", f"mat:delok:{mid}")],
                [btn("Отмена", f"mat:delno:{mid}")],
            ]
        )
    )


@router.callback_query(F.data.startswith("mat:delno:"))
async def cb_delete_no(cb: CallbackQuery) -> None:
    mid = int(cb.data.split(":")[2])
    m = await db.get_material(mid)
    await cb.answer()
    if m:
        await cb.message.edit_reply_markup(reply_markup=card_kb(m))


@router.callback_query(F.data.startswith("mat:delok:"))
async def cb_delete_ok(cb: CallbackQuery) -> None:
    mid = int(cb.data.split(":")[2])
    await db.delete_material(mid)
    await cb.answer("Удалено")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("🗑 Материал удалён.")


# ---------- Поиск ----------
async def start_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SearchState.waiting)
    await message.answer(
        "🔎 Напиши слова для поиска. Ищу по текстам, подписям, названиям файлов, "
        "тегам и предметам. Слово «важно» найдёт помеченное ⭐."
    )


async def run_search(message: Message, query: str) -> None:
    results = await db.search_materials(query)
    if not results:
        await message.answer("Ничего не нашёл. Попробуй другие слова.")
        return
    rows = [[btn(_label(m, with_subject=True), f"mat:open:{m['id']}")] for m in results]
    await message.answer(f"🔎 Найдено: {len(results)}", reply_markup=kb(rows))


@router.message(SearchState.waiting, F.text, ~F.text.startswith("/"))
async def search_typed(message: Message, state: FSMContext) -> None:
    await state.clear()
    await run_search(message, message.text)


@router.message(Command("search"))
async def search_cmd(message: Message, command: CommandObject, state: FSMContext) -> None:
    if command.args:
        await state.clear()
        await run_search(message, command.args)
    else:
        await start_search(message, state)
