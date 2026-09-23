import os

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile

from trackcheck.database.repositories import (
    get_user_name, get_ratings, get_daily_ratings, get_or_create_rank_data,
)
from trackcheck.services.gamification_service import (
    get_rank_name, get_rank_emoji, get_rank_motivation, get_sparks_for_next_rank,
)
from trackcheck.services.stats_service import create_line_chart
from trackcheck.utils.concurrency import run_db
from trackcheck.utils.formatting import create_short_progress_bar
from trackcheck.utils.bot_helpers import delete_message_safe, delete_temp_messages
from trackcheck.keyboards.common import back_reply_keyboard
from trackcheck.keyboards.stats import stats_keyboard, rank_back_keyboard
from trackcheck.runtime import user_last_menu, user_temp_messages, nav_push
from trackcheck.handlers import router


async def _show_stats_choice(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    await state.clear()
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, chat_id, old_menu)
        user_last_menu[user_id] = None
    await delete_temp_messages(bot, user_id, chat_id, keep_ai=True)
    msg = await bot.send_message(chat_id, "📊 Выбери тип статистики:", reply_markup=stats_keyboard())
    user_temp_messages.setdefault(user_id, {})['stats_choice'] = msg.message_id
    nav_push(user_id, "stats")



@router.callback_query(F.data == "menu_stats")
async def handle_stats(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await _show_stats_choice(callback.from_user.id, callback.message.chat.id, bot, state)



@router.callback_query(F.data.startswith("stats:"))
async def show_stats(callback: CallbackQuery, bot: Bot, state: FSMContext):
    period = callback.data.split(":")[1]
    name = await run_db(get_user_name, callback.from_user.id, callback.from_user.first_name)
    temps = user_temp_messages.get(callback.from_user.id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('stats_choice'))
    if period == "week":
        ratings = await run_db(get_ratings, callback.from_user.id, days=7)
        text = f"📊 Статистика за неделю | {name}\n\n"
        for cat, avg, count in ratings:
            bar = create_short_progress_bar(int(avg))
            text += f"{cat}: {avg:.1f}/10 {bar}\n"
        msg = await callback.message.answer(text, reply_markup=rank_back_keyboard())
        user_temp_messages.setdefault(callback.from_user.id, {})['stats_result'] = msg.message_id
    elif period == "month":
        ratings = await run_db(get_ratings, callback.from_user.id, days=30)
        text = f"📊 Статистика за месяц | {name}\n\n"
        for cat, avg, count in ratings:
            bar = create_short_progress_bar(int(avg))
            text += f"{cat}: {avg:.1f}/10 {bar}\n"
        msg = await callback.message.answer(text, reply_markup=rank_back_keyboard())
        user_temp_messages.setdefault(callback.from_user.id, {})['stats_result'] = msg.message_id
    elif period == "chart_week":
        await callback.answer("📈 Генерирую...")
        daily_data = await run_db(get_daily_ratings, callback.from_user.id, days=7)
        if not daily_data:
            msg = await callback.message.answer("❌ Нет данных для графика", reply_markup=rank_back_keyboard())
            user_temp_messages.setdefault(callback.from_user.id, {})['stats_result'] = msg.message_id
            return
        temp_msg = await callback.message.answer("📈 Генерирую график...")
        chart_path = await run_db(create_line_chart, daily_data, callback.from_user.id, days=7)
        try:
            photo = FSInputFile(chart_path)
            await bot.send_photo(
                callback.from_user.id,
                photo,
                caption="📈 Динамика за неделю"
            )
        finally:
            await delete_message_safe(bot, callback.message.chat.id, temp_msg.message_id)
            try:
                os.remove(chart_path)
            except OSError:
                pass
    elif period == "chart_month":
        await callback.answer("📈 Генерирую...")
        daily_data = await run_db(get_daily_ratings, callback.from_user.id, days=30)
        if not daily_data:
            msg = await callback.message.answer("❌ Нет данных для графика", reply_markup=rank_back_keyboard())
            user_temp_messages.setdefault(callback.from_user.id, {})['stats_result'] = msg.message_id
            return
        temp_msg = await callback.message.answer("📈 Генерирую график...")
        chart_path = await run_db(create_line_chart, daily_data, callback.from_user.id, days=30)
        try:
            photo = FSInputFile(chart_path)
            await bot.send_photo(
                callback.from_user.id,
                photo,
                caption="📈 Динамика за месяц"
            )
        finally:
            await delete_message_safe(bot, callback.message.chat.id, temp_msg.message_id)
            try:
                os.remove(chart_path)
            except OSError:
                pass



async def _show_rank(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    await state.clear()
    rank_data = await run_db(get_or_create_rank_data, user_id)
    name = await run_db(get_user_name, user_id)
    rank_id = rank_data['current_rank']
    total = rank_data['total_sparks']
    needed, next_total = get_sparks_for_next_rank(rank_id, total)
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, chat_id, old_menu)
        user_last_menu[user_id] = None
    text = f"""{name}, твой прогресс:

{get_rank_emoji(rank_id)} <b>{get_rank_name(rank_id)}</b>
✨ Искр: {total}/{next_total}
📊 Осталось до следующего ранга: {needed}

<i>{get_rank_motivation(rank_id)}</i>"""
    await delete_temp_messages(bot, user_id, chat_id, keep_ai=True)
    from trackcheck.handlers.notify import notify_settings_keyboard
    from trackcheck.services.notify_service import is_notify_enabled
    from aiogram.types import InlineKeyboardMarkup
    base_rows = back_reply_keyboard().inline_keyboard
    toggle_rows = notify_settings_keyboard(is_notify_enabled(user_id)).inline_keyboard
    msg = await bot.send_message(chat_id, text, parse_mode="HTML",
                                 reply_markup=InlineKeyboardMarkup(
                                     inline_keyboard=toggle_rows + base_rows))
    user_temp_messages.setdefault(user_id, {})['rank'] = msg.message_id
    nav_push(user_id, "rank")



@router.callback_query(F.data == "menu_rank")
async def handle_rank(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await _show_rank(callback.from_user.id, callback.message.chat.id, bot, state)
