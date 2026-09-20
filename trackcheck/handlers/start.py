import asyncio

from aiogram import Bot, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)

from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    save_user_settings, update_streak, get_user_timezone, set_user_timezone,
)
from trackcheck.states.workout import WorkoutSessionState
from trackcheck.utils.bot_helpers import delete_message_safe, delete_message_after_delay
from trackcheck.keyboards.common import timezone_picker_keyboard, with_back_kb
from trackcheck.config import RUSSIAN_TIMEZONES
from trackcheck.runtime import user_welcome_message, user_temp_messages
from trackcheck.handlers.dashboard import send_main_menu
from trackcheck.handlers.workouts import _ws_start_workout
from trackcheck.handlers import router


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
    try:
        await message.delete()
    except:
        pass
    user_id = message.from_user.id
    cursor = db.execute('SELECT first_name FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        welcome_text = """
🌟 *Добро пожаловать в TrackCheck!* 🌟

Я помогу тебе отслеживать ключевые сферы жизни и развивать дисциплину.

📒 *Рефлексия* – оценивай сон, еду, активность, зависание и настрой.
⭐ *Ранги и искры* – за выполнение всех категорий или тренировку.
🏋️ *Тренировки* – создавай категории и упражнения, ставь цели.
🤖 *ИИ-советчик* – задавай вопросы, получай разбор оценок.
🍽 *Диета* – рассчитывай норму калорий, записывай еду, вес, % жира.
📊 *Статистика* – графики и динамика.
🤳 *Анализ фото* – в разделе Тренировки, разбор сильных и слабых сторон телосложения.

👇 Нажми кнопку **«ПОГНАЛИ 💪»**, чтобы начать!
        """
        markup = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
            [InlineKeyboardButton(text="ПОГНАЛИ 💪", callback_data="ws_start")]
        ]))
        msg = await bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)
        user_welcome_message[user_id] = msg.message_id
        asyncio.create_task(delete_welcome_after_delay(user_id, bot, msg.message_id))
        return
    save_user_settings(user_id, message.from_user.username, message.from_user.first_name)
    update_streak(user_id)
    await send_main_menu(bot, user_id, message.chat.id)



async def delete_welcome_after_delay(user_id: int, bot: Bot, msg_id: int):
    await asyncio.sleep(600)
    await delete_message_safe(bot, user_id, msg_id)
    if user_id in user_welcome_message:
        del user_welcome_message[user_id]



@router.callback_query(F.data == "ws_start")
async def handle_start_button(callback: CallbackQuery, bot: Bot, state: FSMContext):
    # Одна кнопка «ПОГНАЛИ» работает и на приветственном экране (онбординг),
    # и на экране плана тренировки (просмотр плана → старт сессии).
    current_state = await state.get_state()
    if current_state == WorkoutSessionState.viewing_plan:
        await _ws_start_workout(callback, bot, state)
    else:
        await _start_onboarding(callback, bot, state)
    await callback.answer()



async def _start_onboarding(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await state.clear()
    # удаляем приветственное сообщение с кнопкой ПОГНАЛИ
    try:
        await callback.message.delete()
    except:
        pass
    if user_id in user_welcome_message:
        del user_welcome_message[user_id]
    save_user_settings(user_id, callback.from_user.username, callback.from_user.first_name)
    update_streak(user_id)
    cursor = db.execute('SELECT timezone FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        msg = await bot.send_message(
            callback.message.chat.id,
            "🕒 Для начала выбери свой часовой пояс — так все даты, стрики и напоминания "
            "будут работать по твоему времени, а не по серверному.\n\n"
            "Позже его можно поменять командой /timezone.",
            reply_markup=timezone_picker_keyboard("onboarding")
        )
        user_temp_messages.setdefault(user_id, {})['timezone_picker'] = msg.message_id
        return
    await send_main_menu(bot, user_id, callback.message.chat.id)



@router.callback_query(F.data.startswith("tz:"))
async def handle_timezone_choice(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    _, tz_name, context = callback.data.split(":")
    set_user_timezone(user_id, tz_name)
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.pop('timezone_picker', None))
    user_temp_messages[user_id] = temps
    label = next((l for l, tz in RUSSIAN_TIMEZONES if tz == tz_name), tz_name)
    await callback.answer(f"Часовой пояс: {label} ✅")
    if context == "onboarding":
        await send_main_menu(bot, user_id, callback.message.chat.id)
    else:
        confirm_msg = await bot.send_message(callback.message.chat.id, f"🕒 Часовой пояс изменён на: {label}")
        asyncio.create_task(delete_message_after_delay(bot, callback.message.chat.id, confirm_msg.message_id, delay=4))



@router.message(Command("timezone"))
async def cmd_timezone(message: Message, bot: Bot):
    try:
        await message.delete()
    except:
        pass
    user_id = message.from_user.id
    current = get_user_timezone(user_id)
    current_label = next((label for label, tz in RUSSIAN_TIMEZONES if tz == current), current)
    msg = await message.answer(
        f"🕒 Текущий часовой пояс: {current_label}\n\nВыбери новый:",
        reply_markup=timezone_picker_keyboard("change")
    )
    user_temp_messages.setdefault(user_id, {})['timezone_picker'] = msg.message_id
