from aiogram import Router
from aiogram.types import TelegramObject

from trackcheck.keyboards.common import BackKeyboardMiddleware


async def _ack_callback_middleware(handler, event: TelegramObject, data: dict):
    """Отвечаем на callback ПЕРВЫМ делом, до тяжёлой работы.

    Раньше callback.answer() вызывался в конце хендлера — пока бот ходил
    в БД/сеть/ИИ (иногда десятки секунд через Turso/Gemini), кнопка в
    телеграме висела в состоянии 'загрузка', и казалось, что бот завис.
    Здесь шлём тихий ack сразу; хендлеры по-прежнему могут вызвать
    callback.answer(text) позже — Telegram просто заменит всплывашку.
    Двойные answer() безвредны, убирать их из хендлеров не нужно."""
    from aiogram.types import CallbackQuery
    if isinstance(event, CallbackQuery):
        try:
            await event.answer()
        except Exception:
            pass
    return await handler(event, data)


router = Router()
router.message.outer_middleware(BackKeyboardMiddleware())
router.callback_query.outer_middleware(BackKeyboardMiddleware())
router.callback_query.middleware(_ack_callback_middleware)

from . import navigation  # noqa: E402,F401
from . import dashboard  # noqa: E402,F401
from . import categories  # noqa: E402,F401
from . import ai  # noqa: E402,F401
from . import start  # noqa: E402,F401
from . import workouts  # noqa: E402,F401
from . import food  # noqa: E402,F401
from . import stats  # noqa: E402,F401
from . import settings  # noqa: E402,F401

__all__ = ["router"]
