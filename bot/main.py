"""Точка входа: python -m bot.main

Два режима:
  * WEBHOOK (на бесплатном хостинге Render): Telegram сам присылает сообщения на адрес сервиса,
    это будит уснувший сервис. Включается, если задан WEBHOOK_BASE_URL или RENDER_EXTERNAL_URL.
  * POLLING (на компьютере или своём сервере): бот сам опрашивает Telegram.
"""
import asyncio
import hashlib
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import backup, db
from .config import get_settings
from .handlers import archive, export, fallback, materials, pdf_note, start, subjects, tags, teachers
from .keyboards import main_menu
from .middlewares import OwnerOnlyMiddleware

log = logging.getLogger("bot")


def build_dispatcher(owner_id: int) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    owner_only = OwnerOnlyMiddleware(owner_id)
    dp.message.outer_middleware(owner_only)
    dp.callback_query.outer_middleware(owner_only)
    # Порядок важен: меню первым, запасные обработчики последними
    for module in (start, materials, pdf_note, archive, tags, teachers, subjects, export, fallback):
        dp.include_router(module.router)
    return dp


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_web_app(dp: Dispatcher, bot: Bot, settings) -> tuple[web.Application, str]:
    path = "/tg/" + hashlib.sha256((settings.bot_token + ":path").encode()).hexdigest()[:32]
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)  # сюда будет стучаться пингер
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=settings.secret).register(app, path=path)
    return app, path


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # 1. Если базы нет (диск стёрли), восстанавливаем из закреплённого бэкапа.
    #    При временном сбое Telegram не стартуем, чтобы пустая база не затёрла бэкап.
    status = "error"
    for _ in range(5):
        status = await backup.restore_if_missing(bot, settings)
        if status != "error":
            break
        await asyncio.sleep(5)
    if status == "error":
        raise RuntimeError("Не удалось проверить бэкап. Не запускаюсь, чтобы не потерять данные.")
    await db.init(settings.db_path)

    dp = build_dispatcher(settings.owner_id)

    # 2. Бэкап: каждую минуту проверяем изменения + ежедневный контрольный
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        backup.backup_if_dirty, IntervalTrigger(seconds=60),
        args=[bot, settings], id="dirty_backup", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        backup.make_backup, CronTrigger(hour=settings.backup_hour, minute=0),
        args=[bot, settings], id="daily_backup", misfire_grace_time=3600, coalesce=True,
    )
    scheduler.start()

    note = {
        "restored": "♻️ Сервер перезапускался. Я восстановил базу из последнего бэкапа.",
        "none": "ℹ️ Запустился с чистой базой (бэкап не найден).",
        "exists": None,
    }[status]
    if note:
        try:
            await bot.send_message(settings.owner_id, note, reply_markup=main_menu())
        except Exception:
            log.warning("Не смог написать владельцу (он ещё не нажимал Start?)")

    stop = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
    except (NotImplementedError, RuntimeError):
        pass  # Windows: остановка через Ctrl+C

    runner = None
    polling_task = None
    try:
        if settings.base_url:
            app, path = build_web_app(dp, bot, settings)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", settings.port).start()
            await bot.set_webhook(
                url=settings.base_url + path,
                secret_token=settings.secret,
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=False,
            )
            log.info("Бот запущен (webhook), порт %s", settings.port)
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            polling_task = asyncio.create_task(
                dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False)
            )
            log.info("Бот запущен (polling)")
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        log.info("Останавливаюсь…")
        scheduler.shutdown(wait=False)
        if polling_task:
            try:
                await dp.stop_polling()
            except RuntimeError:
                pass
            await polling_task
        if runner:
            await runner.cleanup()
        # Последний бэкап, если успели что-то изменить
        if db.is_dirty():
            await backup.make_backup(bot, settings)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
