from aiogram import BaseMiddleware, Bot
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           TelegramObject)

from trackcheck.config import BACK_BUTTON_TEXT, BACK_BUTTON_CALLBACK, RUSSIAN_TIMEZONES


def _back_button_row():
    return [InlineKeyboardButton(text=BACK_BUTTON_TEXT, callback_data=BACK_BUTTON_CALLBACK)]



def _has_back_button(rows) -> bool:
    for row in rows or []:
        for btn in row or []:
            if getattr(btn, "callback_data", None) == BACK_BUTTON_CALLBACK:
                return True
    return False



def with_back_kb(rows):
    """Принимает список строк inline-кнопок и дописывает вниз строку с
    универсальной кнопкой «🔙 Назад». Идемпотентно: если кнопка уже есть,
    возвращает исходный список без изменений."""
    rows = rows or []
    if _has_back_button(rows):
        return rows
    rows = [row for row in rows]
    rows.append(_back_button_row())
    return rows



def back_reply_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[_back_button_row()])



async def ensure_back_keyboard(bot: Bot, chat_id: int, user_id: int):
    """Раньше кнопка «Назад» жила на отдельном постоянном сообщении с
    reply-клавиатурой (Telegram разрешает только одну клавиатуру на сообщение).
    Теперь она прикреплена к каждому сообщению с inline-кнопками через
    with_back_kb(), так что отдельное сообщение больше не нужно."""
    return



class BackKeyboardMiddleware(BaseMiddleware):
    """Кнопка «Назад» теперь прикрепляется к каждому сообщению с inline-кнопками
    прямо при его отправке (через with_back_kb() в каждой клавиатурной функции и
    в _screen_send), поэтому отдельное сообщение-носитель больше не нужно.
    Миддлварь оставлена как no-op, чтобы не ломать существующие вызовы
    ensure_back_keyboard()."""
    async def __call__(self, handler, event: TelegramObject, data: dict):
        return await handler(event, data)



def timezone_picker_keyboard(context: str = "onboarding"):
    rows = [[InlineKeyboardButton(text=label, callback_data=f"tz:{tz}:{context}")] for label, tz in RUSSIAN_TIMEZONES]
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(rows))



def retry_ai_keyboard(action: str):
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🔄 Попробовать еще раз", callback_data=f"retry_ai:{action}")]
    ]))
