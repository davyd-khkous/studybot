"""Выгрузка всех конспектов предмета одним PDF."""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from .. import db, pdf_tools
from ..utils import KIND_NAMES, fmt_date, safe_filename, short

router = Router()
log = logging.getLogger(__name__)
MAX_BYTES = 49 * 1024 * 1024


async def _download(bot: Bot, file_id: str) -> bytes | None:
    try:
        buf = await bot.download(file_id)
        return buf.read()
    except Exception:
        log.exception("Не удалось скачать файл")
        return None


@router.callback_query(F.data.startswith("exp:"))
async def export_subject(cb: CallbackQuery, bot: Bot) -> None:
    sid = int(cb.data.split(":")[1])
    subj = await db.get_subject(sid)
    if not subj:
        await cb.answer("Предмет не найден", show_alert=True)
        return
    mats = await db.list_materials(sid, "all")
    if not mats:
        await cb.answer("В этом предмете пока нет материалов", show_alert=True)
        return
    await cb.answer("Готовлю PDF…")
    chat_id = cb.message.chat.id
    status = await cb.message.answer(
        f"⏳ Собираю PDF по предмету «{subj['name']}» ({len(mats)} шт.). Это может занять до минуты."
    )
    await bot.send_chat_action(chat_id, "upload_document")

    mats.sort(key=lambda m: (m["date"], m["id"]))
    parts: list[tuple[str, bytes]] = []
    toc: list[str] = []
    notes: list[str] = []

    for i, m in enumerate(mats, start=1):
        d = fmt_date(m["date"])
        kind = KIND_NAMES.get(m["kind"], "файл")
        star = " [важно]" if m["important"] else ""
        tags = f"Теги: {m['tags_str']}" if m.get("tags_str") else ""
        label = m.get("file_name") or short(m.get("caption") or m.get("text") or kind, 50)
        toc.append(f"{i}. {d} - {kind}{star} - {label}")
        heading = f"{i}. {d}{star}" + (f"  {tags}" if tags else "")

        try:
            if m["kind"] == "text":
                first = (m["text"] or "").strip().splitlines()[0:1]
                title = short(first[0], 70) if first else f"Конспект {i}"
                seg = await asyncio.to_thread(
                    pdf_tools.text_pdf_bytes, f"{i}. {title}", d, m["text"] or "", tags
                )
            elif m["kind"] == "photo":
                img = await _download(bot, m["file_id"])
                if img is None:
                    raise RuntimeError("download")
                cap = f" - {m['caption']}" if m.get("caption") else ""
                seg = await asyncio.to_thread(pdf_tools.photo_pdf_bytes, img, heading + cap)
            elif m["kind"] == "pdf":
                data = await _download(bot, m["file_id"])
                if data is None:
                    raise RuntimeError("download")
                seg = data
            else:
                seg = await asyncio.to_thread(
                    pdf_tools.note_pdf_bytes,
                    heading,
                    f"Файл «{m.get('file_name') or 'без имени'}» не PDF, поэтому не вложен. "
                    "Он остаётся в архиве бота.",
                )
                notes.append(f"{i}. {m.get('file_name') or 'файл'} (не PDF)")
        except Exception:
            seg = await asyncio.to_thread(
                pdf_tools.note_pdf_bytes, heading, "Не удалось получить этот файл из Telegram."
            )
            notes.append(f"{i}. {label} (не удалось получить)")
        parts.append((f"{i}. {label}", seg))

    toc_pdf = await asyncio.to_thread(
        pdf_tools.toc_pdf_bytes, f"{subj['name']}: конспекты", toc
    )
    merged, failed = await asyncio.to_thread(
        pdf_tools.merge_pdfs, [("Содержание", toc_pdf)] + parts
    )
    notes += [f"{f} (PDF защищён или повреждён)" for f in failed]

    try:
        await status.delete()
    except Exception:
        pass
    if len(merged) > MAX_BYTES:
        await bot.send_message(
            chat_id,
            "Получился файл больше 49 МБ, Telegram такой не принимает. "
            "Выгрузи материалы по частям: в архиве выбери период или тег.",
        )
        return
    await bot.send_document(
        chat_id,
        BufferedInputFile(merged, filename=f"{safe_filename(subj['name'])}_конспекты.pdf"),
        caption=f"📤 {subj['name']}: {len(mats)} материалов",
    )
    if notes:
        await bot.send_message(chat_id, "Не всё удалось вложить:\n" + "\n".join(notes))
