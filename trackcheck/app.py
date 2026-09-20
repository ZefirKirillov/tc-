import asyncio
import signal
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from trackcheck import runtime
from trackcheck.config import BOT_TOKEN, RUSSIAN_TIMEZONES
from trackcheck.database.connection import db, init_db
from trackcheck.utils.logging import (log_db_persistence_diagnostics,
                                      log_ratings_ai_diagnostics)
from trackcheck.services.tracker_service import finalize_daily_ratings_for_timezone
from trackcheck.handlers import router


async def main():
    print("[BOOT] Старт...")
    init_db()
    print("[BOOT] База инициализирована")
    log_db_persistence_diagnostics()
    log_ratings_ai_diagnostics()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("[BOOT] Диспетчер готов")

    bot = Bot(token=BOT_TOKEN)
    print("[BOOT] Бот создан")

    scheduler = AsyncIOScheduler()
    for _, tz_name in RUSSIAN_TIMEZONES:
        scheduler.add_job(
            finalize_daily_ratings_for_timezone, 'cron',
            hour=23, minute=55, timezone=ZoneInfo(tz_name),
            args=[tz_name], id=f"finalize_ratings_{tz_name}", replace_existing=True
        )
    scheduler.start()
    runtime.scheduler = scheduler
    print("[BOOT] Планировщик запущен")

    await bot.delete_webhook(drop_pending_updates=True)
    print("[BOOT] Webhook удалён")

    polling_task = asyncio.create_task(dp.start_polling(bot))
    print("[BOOT] Polling запущен")

    stop_signal = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_signal.set)
        except (NotImplementedError, AttributeError):
            signal.signal(sig, lambda *_: stop_signal.set())

    await stop_signal.wait()
    print("Получен сигнал остановки...")

    polling_task.cancel()
    try:
        await asyncio.gather(polling_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    await bot.session.close()
    db.close()
    if scheduler:
        scheduler.shutdown()
    print("Бот остановлен")
