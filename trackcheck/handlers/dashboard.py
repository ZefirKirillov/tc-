from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from trackcheck.database.repositories import (
    get_today_ratings, get_or_create_workout_data, get_or_create_rank_data,
    get_streak, get_diet_profile, get_today_calories, get_urgent_tasks_for_menu,
)
from trackcheck.services.gamification_service import (
    get_rank_name, get_rank_emoji, get_sparks_for_next_rank,
)
from trackcheck.utils.formatting import create_new_progress_bar
from trackcheck.utils.bot_helpers import delete_temp_messages
from trackcheck.utils.concurrency import run_db
from trackcheck.keyboards.common import ensure_back_keyboard
from trackcheck.keyboards.dashboard import main_menu_keyboard, urgent_tasks_keyboard
from trackcheck.runtime import user_last_menu, user_temp_messages, nav_push
from trackcheck.handlers import router


def format_main_menu(user_id: int) -> str:
    today_ratings = get_today_ratings(user_id)
    workout_data = get_or_create_workout_data(user_id)
    rank_data = get_or_create_rank_data(user_id)
    streak = get_streak(user_id)
    profile = get_diet_profile(user_id)
    if profile:
        today_cal = get_today_calories(user_id)
        daily_goal = profile['daily_calories']
        percent = (today_cal / daily_goal * 100) if daily_goal > 0 else 0
        calories_line = f"🍽 Калории: {int(today_cal)}/{int(daily_goal)} ({int(percent)}%)"
    else:
        calories_line = "🍽 Диета не настроена"

    categories = {
        'сон': '😴',
        'еда': '🍽',
        'активность': '💪',
        'зависание': '🎮',
        'настрой': '🎯'
    }

    rank_id = rank_data['current_rank']
    rank_name = get_rank_name(rank_id)
    rank_emoji = get_rank_emoji(rank_id)

    lines = [f"┌─ TrackCheck "]
    lines.append("│")
    lines.append(f"│ <i>{rank_emoji} {rank_name} {rank_emoji}</i>")
    lines.append("│")

    for cat_key, emoji in categories.items():
        rating = today_ratings.get(cat_key)
        if rating:
            bar = create_new_progress_bar(rating)
            lines.append(f"│ {emoji} {bar}")
        else:
            lines.append(f"│ {emoji} {create_new_progress_bar(0)}")

    lines.append("│")

    total_sparks = rank_data['total_sparks']
    sparks_needed, next_total = get_sparks_for_next_rank(rank_id, total_sparks)

    lines.append(f"│ 🏋️ {workout_data['current_count']}/{workout_data['monthly_goal']} | ✨ {total_sparks}/{next_total} искр")
    lines.append(f"│ {calories_line}")
    lines.append(f"│ 🔥 Стрик: {streak} дней")
    lines.append("└─────────────────────")

    return "\n".join(lines)



async def send_main_menu(bot: Bot, user_id: int, chat_id: int):
    # Reply-клавиатура с «🔙 Назад» не может жить на сообщении с inline-кнопками —
    # держим её на отдельном постоянном сообщении.
    await ensure_back_keyboard(bot, chat_id, user_id)
    nav_push(user_id, "main")
    # Кнопки должны отвечать мгновенно: тяжёлые синхронные запросы к БД
    # (через Turso — это сеть) уходят в пул потоков, а не блокируют event loop.
    try:
        text = await run_db(format_main_menu, user_id)
    except Exception as e:
        import traceback
        print(f"[BOT] ОШИБКА format_main_menu: {e}")
        traceback.print_exc()
        text = None
    try:
        old_menu = user_last_menu.get(user_id)
        if old_menu:
            try:
                await bot.delete_message(chat_id, old_menu)
            except Exception as e:
                print(f"[BOT] Не удалось удалить старое меню: {e}")
        # Удаляем временные сообщения, сохраняя важные (фото, ИИ, замеры)
        await delete_temp_messages(bot, user_id, chat_id, keep_ai=True)
        if text is None:
            text = "┌─ TrackCheck\n│\n│ ⚠️ Не удалось загрузить данные.\n└─────────────────────"
        msg = await bot.send_message(chat_id, text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        user_last_menu[user_id] = msg.message_id
        # Отправляем срочные задачи отдельным сообщением если есть
        try:
            urgent = await run_db(get_urgent_tasks_for_menu, user_id)
        except Exception as e:
            print(f"[BOT] ОШИБКА get_urgent_tasks_for_menu: {e}")
            urgent = []
        if urgent:
            kb = urgent_tasks_keyboard(urgent, user_id)
            tasks_msg = await bot.send_message(chat_id, "⚡ Срочные задачи:", reply_markup=kb)
            user_temp_messages.setdefault(user_id, {})['urgent_tasks'] = tasks_msg.message_id
        else:
            user_temp_messages.setdefault(user_id, {}).pop('urgent_tasks', None)
    except Exception as e:
        import traceback
        print(f"[BOT] ОШИБКА в send_main_menu: {e}")
        traceback.print_exc()
        # Последний шанс: показываем меню-заглушку с кнопками (без «режима
        # восстановления» как текста — чтобы не пугать пользователя), сами
        # кнопки при этом работают: каждый экран грузит свои данные отдельно.
        try:
            msg = await bot.send_message(chat_id, "┌─ TrackCheck\n│\n│ ⚠️ Данные временно недоступны, выбери раздел:\n└─────────────────────",
                                         reply_markup=main_menu_keyboard())
            user_last_menu[user_id] = msg.message_id
        except Exception as e2:
            print(f"[BOT] Критическая ошибка: {e2}")



@router.callback_query(F.data == "back_to_main")
@router.callback_query(F.data == "back_to_main_from_ai")
async def back_to_main_callback(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await state.clear()
    try:
        await callback.message.delete()
    except:
        pass
    # Удаляем временные сообщения, сохраняя важные
    await delete_temp_messages(bot, user_id, callback.message.chat.id, keep_ai=True)
    # Убираем инлайн кнопки у сохранённых сообщений
    temps = user_temp_messages.get(user_id, {})
    for key in ['photo_analysis_result', 'photo_user', 'body_fat_measurements', 'body_fat_result']:
        if key in temps:
            try:
                await bot.edit_message_reply_markup(callback.message.chat.id, temps[key])
            except:
                pass
    await send_main_menu(bot, user_id, callback.message.chat.id)
