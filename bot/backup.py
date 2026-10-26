"""Бэкап базы в личный чат с ботом и восстановление при старте.

Как это работает:
  * бот держит в чате с тобой ОДНО закреплённое сообщение с файлом базы;
  * после любого изменения (через ~30 секунд тишины) файл в этом сообщении обновляется;
  * если при запуске базы нет (бесплатный хостинг стирает диск при перезапуске),
    бот находит закреплённое сообщение, скачивает файл и восстанавливает базу.
Поэтому не удаляй закреплённый бэкап и не закрепляй в чате с ботом другие сообщения.
"""
import asyncio
import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile, InputMediaDocument

from . import db
from .config import Settings

log = logging.getLogger(__name__)
PREFIX = "studybot_backup"
QUIET_SECONDS = 30


def _snapshot(src_path: str, dest_path: str) -> None:
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dest_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _is_valid_db(path: str) -> bool:
    try:
        con = sqlite3.connect(path)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = {
                r[0]
                for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            return ok and "subjects" in tables and "materials" in tables
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _is_backup_message(msg) -> bool:
    return bool(
        msg
        and getattr(msg, "document", None)
        and (msg.document.file_name or "").startswith(PREFIX)
    )


async def make_backup(bot: Bot, settings: Settings, force: bool = False) -> str:
    """Возвращает 'ok', 'empty' (база пустая, пропустили) или 'error'."""
    try:
        if not force and await db.is_empty():
            log.info("База пуста, бэкап пропущен (чтобы не затереть старый)")
            return "empty"

        stamp = datetime.now(ZoneInfo(settings.timezone))
        filename = f"{PREFIX}_{stamp:%Y%m%d_%H%M%S}.db"
        caption = (
            f"💾 Бэкап базы · {stamp:%d.%m.%Y %H:%M}\n"
            "Не удаляй и не открепляй это сообщение: по нему бот восстанавливает базу."
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = str(Path(tmp) / filename)
            await asyncio.to_thread(_snapshot, settings.db_path, dest)

            pinned = None
            try:
                chat = await bot.get_chat(settings.owner_id)
                if _is_backup_message(chat.pinned_message):
                    pinned = chat.pinned_message
            except Exception:
                log.exception("Не удалось получить закреплённое сообщение")

            # 1) Пробуем обновить файл в уже закреплённом сообщении
            if pinned:
                try:
                    await bot.edit_message_media(
                        media=InputMediaDocument(
                            media=FSInputFile(dest, filename=filename), caption=caption
                        ),
                        chat_id=settings.owner_id,
                        message_id=pinned.message_id,
                    )
                    log.info("Бэкап обновлён")
                    return "ok"
                except TelegramBadRequest as e:
                    if "not modified" in str(e):
                        return "ok"
                    log.warning("Не получилось обновить сообщение (%s), шлю новое", e)

            # 2) Иначе отправляем новое сообщение и закрепляем
            msg = await bot.send_document(
                settings.owner_id,
                FSInputFile(dest, filename=filename),
                caption=caption,
                disable_notification=True,
            )
        await bot.pin_chat_message(
            settings.owner_id, msg.message_id, disable_notification=True
        )
        if pinned:
            try:
                await bot.unpin_chat_message(settings.owner_id, message_id=pinned.message_id)
            except Exception:
                pass
        log.info("Бэкап отправлен новым сообщением")
        return "ok"
    except Exception:
        log.exception("Ошибка бэкапа")
        return "error"


async def backup_if_dirty(bot: Bot, settings: Settings) -> None:
    """Запускается каждую минуту: если база менялась, обновляем бэкап."""
    if not db.is_dirty(QUIET_SECONDS):
        return
    db.clear_dirty()
    if await make_backup(bot, settings) == "error":
        db.mark_dirty()  # попробуем ещё раз через минуту


async def restore_if_missing(bot: Bot, settings: Settings) -> str:
    """Возвращает 'exists', 'restored', 'none' или 'error' (временный сбой, надо повторить)."""
    path = Path(settings.db_path)
    if path.exists() and path.stat().st_size > 0:
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".restore")
    try:
        try:
            chat = await bot.get_chat(settings.owner_id)
        except (TelegramBadRequest, TelegramForbiddenError) as e:
            # Ты ещё не нажимал Start у бота: бэкапов быть не может
            log.info("Чат с владельцем недоступен (%s), начинаю с пустой базы", e)
            return "none"
        msg = chat.pinned_message
        if not _is_backup_message(msg):
            log.info("Закреплённого бэкапа нет, начинаю с пустой базы")
            return "none"
        await bot.download(msg.document.file_id, destination=tmp)
        if _is_valid_db(str(tmp)):
            tmp.replace(path)
            log.info("База восстановлена из бэкапа")
            return "restored"
        log.error("Файл бэкапа повреждён, начинаю с пустой базы")
        return "none"
    except Exception:
        log.exception("Не удалось восстановить базу (временный сбой?)")
        return "error"
    finally:
        if tmp.exists():
            tmp.unlink()
