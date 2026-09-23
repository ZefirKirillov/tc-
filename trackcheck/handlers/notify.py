"""Хендлеры уведомлений: кнопка mute + тумблер вкл/выкл."""
from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.services.notify_service import (
    mute_until_morning, is_notify_enabled, set_notify_enabled,
    delete_last_notification,
)
from trackcheck.handlers import router


@router.callback_query(F.data == "notify_mute")
async def notify_mute_press(callback: CallbackQuery):
    user_id = callback.from_user.id
    mute_until_morning(user_id)
    await delete_last_notification(callback.bot, user_id)
    try:
        msg = await callback.bot.send_message(user_id, "🔕 Хорошо, до 08:00 не побеспокою.")
        import asyncio
        from trackcheck.utils.bot_helpers import delete_message_after_delay
        asyncio.create_task(delete_message_after_delay(callback.bot, user_id, msg.message_id, delay=10))
    except Exception:
        pass
    await callback.answer("До утра тихо 🤫")


def notify_settings_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    label = "🔔 Напоминания: ВКЛ" if enabled else "🔕 Напоминания: ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data="notify_toggle")],
    ])


@router.callback_query(F.data == "notify_toggle")
async def notify_toggle_press(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_state = not is_notify_enabled(user_id)
    set_notify_enabled(user_id, new_state)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=notify_settings_keyboard(new_state))
    except Exception:
        pass
    if not new_state:
        await delete_last_notification(callback.bot, user_id)
    await callback.answer("Напоминания включены 🔔" if new_state else "Напоминания выключены 🔕")
