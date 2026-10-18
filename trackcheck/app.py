import asyncio
import os
import signal
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from trackcheck import runtime
from trackcheck.config import BOT_TOKEN, RUSSIAN_TIMEZONES
from trackcheck.database.connection import db, init_db
from trackcheck.web.server import start_web_server
from trackcheck.utils.logging import (log_db_persistence_diagnostics,
                                       log_ratings_ai_diagnostics)
from trackcheck.services.tracker_service import (finalize_daily_ratings_for_timezone,
                                                 start_daily_ratings_for_timezone)
from trackcheck.handlers import router


async def setup_bot_entry_points(bot: Bot):
    """Кнопка «TrackCheck» слева от поля ввода (открывает Mini App) + список команд.
    Онбординг ссылается на эту кнопку. Ошибка здесь не должна мешать запуску бота."""
    from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo
    from trackcheck.config import MINIAPP_URL
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="TrackCheck", web_app=WebAppInfo(url=MINIAPP_URL)))
        await bot.set_my_commands([
            BotCommand(command="app", description="Открыть приложение"),
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="timezone", description="Часовой пояс"),
        ])
        print("[BOOT] Кнопка Mini App и команды установлены")
    except Exception as e:
        print(f"[BOOT] Не удалось установить кнопку меню/команды: {e}")


# BOT_MODE:
#   polling (default) — the whole bot here: Telegram polling, scheduler, Mini App, API.
#   worker            — the bot's handlers run on Telegram Serverless (serverless/);
#                       this process keeps the scheduled jobs and the AI/chart relay.
#   relay             — only the AI/chart relay (a test service for the serverless bot).
BOT_MODE = os.getenv("BOT_MODE", "polling").strip().lower()


async def main():
    print(f"[BOOT] Старт... (BOT_MODE={BOT_MODE})")
    if BOT_MODE == "relay":
        await _run_until_signal(await start_web_server())
        return
    init_db()
    print("[BOOT] База инициализирована")
    log_db_persistence_diagnostics()
    log_ratings_ai_diagnostics()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("[BOOT] Диспетчер готов")

    bot = Bot(token=BOT_TOKEN)
    print("[BOOT] Бот создан")
    if BOT_MODE == "polling":
        # In worker mode the serverless bot owns the menu button and commands.
        await setup_bot_entry_points(bot)

    scheduler = AsyncIOScheduler()
    for _, tz_name in RUSSIAN_TIMEZONES:
        scheduler.add_job(
            finalize_daily_ratings_for_timezone, 'cron',
            hour=23, minute=55, timezone=ZoneInfo(tz_name),
            args=[tz_name], id=f"finalize_ratings_{tz_name}", replace_existing=True
        )
        scheduler.add_job(
            start_daily_ratings_for_timezone, 'cron',
            hour=0, minute=1, timezone=ZoneInfo(tz_name),
            args=[tz_name], id=f"start_ratings_{tz_name}", replace_existing=True
        )

    async def _notify_hourly():
        from trackcheck.services.notify_service import hourly_job
        try:
            await hourly_job(bot)
        except Exception as e:
            print(f"[NOTIFY] hourly tick fail: {e}")

    async def _notify_usual():
        from trackcheck.services.notify_service import usual_job
        try:
            await usual_job(bot)
        except Exception as e:
            print(f"[NOTIFY] usual tick fail: {e}")

    # часовой цикл шлёт только важное, 6-часовой — всё остальное; слот один
    scheduler.add_job(_notify_hourly, 'interval', hours=1,
                      id="notify_hourly", replace_existing=True)
    scheduler.add_job(_notify_usual, 'interval', hours=6,
                      id="notify_usual", replace_existing=True)
    scheduler.start()
    runtime.scheduler = scheduler
    print("[BOOT] Планировщик запущен")

    health_runner = await start_web_server()

    polling_task = None
    if BOT_MODE == "polling":
        await bot.delete_webhook(drop_pending_updates=True)
        print("[BOOT] Webhook удалён")
        polling_task = asyncio.create_task(dp.start_polling(bot))
        print("[BOOT] Polling запущен")
    else:
        # The webhook belongs to Telegram Serverless — never delete it here.
        print("[BOOT] Worker: polling выключен, работают планировщик и relay")

    stop_signal = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_signal.set)
        except (NotImplementedError, AttributeError):
            signal.signal(sig, lambda *_: stop_signal.set())

    await stop_signal.wait()
    print("Получен сигнал остановки...")

    if polling_task:
        polling_task.cancel()
        try:
            await asyncio.gather(polling_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    await health_runner.cleanup()
    await bot.session.close()
    db.close()
    if scheduler:
        scheduler.shutdown()
    print("Бот остановлен")


async def _run_until_signal(runner):
    stop_signal = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_signal.set)
        except (NotImplementedError, AttributeError):
            signal.signal(sig, lambda *_: stop_signal.set())
    await stop_signal.wait()
    await runner.cleanup()
