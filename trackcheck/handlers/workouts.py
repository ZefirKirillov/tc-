import asyncio
import io
import json
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, F
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from PIL import Image
from google import genai
from google.genai import types

from trackcheck.config import WEEKDAY_KEY, WEEKDAY_RU
from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    get_ai_plan, save_ai_plan, delete_all_workout_data, get_today_session,
    create_today_session, get_session_exercise_logs, get_previous_same_session,
    get_next_training_day, get_weekly_workout_progress,
    get_current_week_session_key, get_today_plan, update_plan_json,
    update_session_exercise_plan, set_workout_goal, add_workout, add_spark,
    update_streak, get_user_name,
    _deduct_spark_for_skip,
)
from trackcheck.states.workout import WorkoutState, AIPlanState, WorkoutSessionState
from trackcheck.services.ai_service import (
    gemini_generate_plan, gemini_parse_manual_plan, _fallback_parse_plan,
    gemini_edit_plan, gemini_parse_exercise_result, gemini_session_feedback,
    gemini_adapt_next_session, gemini_monthly_review,
)
from trackcheck.services.tracker_service import sync_activity_rating_for_today
from trackcheck.services.workout_service import (
    _format_full_plan, _format_session_detail, apply_monthly_changes,
)
from trackcheck.services.gamification_service import get_rank_name
from trackcheck.services.chart_service import build_workout_progress_chart
from trackcheck.utils.concurrency import run_in_thread, run_db
from trackcheck.utils.dates import user_today_str, user_weekday
from trackcheck.utils.formatting import create_workout_progress_bar
from trackcheck.utils.validation import parse_reps_input
from trackcheck.utils.bot_helpers import (
    delete_message_safe, delete_temp_messages, send_temp_message,
)
from trackcheck.keyboards.common import (
    with_back_kb, back_reply_keyboard, retry_ai_keyboard,
)
from trackcheck.keyboards.ai import (
    photo_analysis_cancel_keyboard, photo_analysis_back_keyboard,
)
from trackcheck.keyboards.workouts import (
    workout_main_keyboard, workout_categories_keyboard, workout_exercises_keyboard,
    workout_action_choice_keyboard, workout_continue_keyboard,
    workout_exercise_goal_keyboard, workout_manage_reply_keyboard,
    workout_category_actions_keyboard, workout_exercise_actions_keyboard,
    wp_mode_keyboard, wp_goal_keyboard, wp_level_keyboard, wp_days_keyboard,
    wp_plan_review_keyboard, wp_plan_review_keyboard_manual,
    ws_today_keyboard, ws_exercise_keyboard, ws_skip_day_keyboard,
    ws_rest_day_keyboard, wp_settings_keyboard,
)
from trackcheck.runtime import (user_temp_messages, user_last_menu,
                                user_history_page, user_nav, nav_push)
from trackcheck.handlers.dashboard import send_main_menu
from trackcheck.handlers import router


@router.callback_query(F.data == "menu_photo_analysis")
async def handle_photo_analysis_start(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await state.clear()
    await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
    intro_msg = await callback.message.answer(
        "📸 Отправь фото для анализа телосложения.\n\nИли нажми «❌ Отмена».",
        reply_markup=photo_analysis_cancel_keyboard()
    )
    user_temp_messages.setdefault(callback.from_user.id, {})['photo_intro'] = intro_msg.message_id
    await state.set_state("waiting_for_photo")
    await callback.answer()



@router.message(F.photo, StateFilter("waiting_for_photo"))
async def analyze_photo(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    chat_id = message.chat.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.get('photo_intro'))
    if 'photo_intro' in temps:
        del temps['photo_intro']
    # Сохраняем фото пользователя (не удаляем)
    temps['photo_user'] = message.message_id
    user_temp_messages[user_id] = temps

    status_msg = await message.answer("🔍 Загружаю фото...")
    statuses = ["🔍 Анализирую телосложение...", "💪 Оцениваю пропорции...", "📝 Готовлю разбор..."]
    for s in statuses:
        await asyncio.sleep(1)
        try:
            await status_msg.edit_text(s)
        except:
            pass

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    buffer = await bot.download_file(file.file_path)
    if buffer is None or not hasattr(buffer, 'read'):
        await status_msg.edit_text("❌ Не удалось загрузить фото.")
        await state.clear()
        await show_workout_main_menu(user_id, chat_id, bot)
        return
    if hasattr(buffer, 'seek'):
        buffer.seek(0)
    image = Image.open(buffer)
    img_buffer = io.BytesIO()
    image.save(img_buffer, format='PNG')
    image_bytes = img_buffer.getvalue()

    prompt = """Кратко проанализируй телосложение на фото. Формат ответа:
• Сильные стороны (1-2 предложения)
• Слабые стороны (1-2 предложения)
• Рекомендации (2-3 конкретных совета)
Без воды, по делу, макс 150 слов."""
    await state.update_data(
        retry_photo_bytes=image_bytes,
        retry_photo_prompt=prompt,
        retry_action="photo_analysis"
    )
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        analysis = "❌ ИИ недоступен (нет API-ключа)."
    else:
        try:
            client = genai.Client(api_key=api_key)
            image_part = types.Part.from_bytes(data=image_bytes, mime_type='image/png')
            response = await run_in_thread(
                client.models.generate_content,
                model='gemini-3.6-flash',
                contents=[prompt, image_part],
                config=types.GenerateContentConfig(max_output_tokens=2048)
            )
            text = getattr(response, 'text', None)
            analysis = text.strip() if text else (response.candidates[0].content.parts[0].text if response.candidates and response.candidates[0].content.parts else "❌ Нет ответа")
        except Exception as e:
            import traceback
            traceback.print_exc()
            analysis = f"❌ Ошибка: {str(e)[:100]}"

    await delete_message_safe(bot, chat_id, status_msg.message_id)
    if analysis.startswith("❌"):
        result_msg = await message.answer(
            analysis + "\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("photo_analysis")
        )
        user_temp_messages.setdefault(user_id, {})['photo_analysis_result'] = result_msg.message_id
        await state.clear()
        return
    result_msg = await message.answer(analysis, reply_markup=photo_analysis_back_keyboard())
    user_temp_messages.setdefault(user_id, {})['photo_analysis_result'] = result_msg.message_id
    await state.clear()



@router.callback_query(F.data == "photo_analysis_cancel", StateFilter("waiting_for_photo"))
async def photo_analysis_cancel(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('photo_intro'))
    # НЕ удаляем фото пользователя и анализ ИИ при отмене
    await state.clear()
    await show_workout_main_menu(user_id, callback.message.chat.id, bot)
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()



@router.callback_query(F.data == "photo_analysis_back")
async def photo_analysis_back(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await delete_temp_messages(bot, user_id, callback.message.chat.id, keep_ai=True)
    # Убираем инлайн кнопки у сохранённых сообщений (включая сам результат анализа)
    temps = user_temp_messages.get(user_id, {})
    for key in ['photo_analysis_result', 'photo_user', 'body_fat_measurements', 'body_fat_result']:
        if key in temps:
            try:
                await bot.edit_message_reply_markup(callback.message.chat.id, temps[key])
            except:
                pass
    await state.clear()
    await send_main_menu(bot, user_id, callback.message.chat.id)
    await callback.answer()



@router.message(StateFilter("waiting_for_photo"), F.text)
async def photo_timeout(message: Message, bot: Bot, state: FSMContext):
    await message.answer("Я ждал фото. Отмена.")
    await state.clear()
    await show_workout_main_menu(message.from_user.id, message.chat.id, bot)



async def show_workout_main_menu(user_id: int, chat_id: int, bot: Bot):
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.pop('workout_menu', None))
    await delete_message_safe(bot, chat_id, temps.pop('tasks_menu', None))
    user_temp_messages[user_id] = temps

    done_week, plan_week = await run_db(get_weekly_workout_progress, user_id)
    week_bar = create_workout_progress_bar(done_week, plan_week if plan_week else 1)
    today_wd = WEEKDAY_RU[user_weekday(user_id)]
    date_str = user_today_str(user_id, '%d.%m.%Y')

    # Show today's completed exercises
    today_str = ""
    today_session = await run_db(get_today_session, user_id)
    if today_session and today_session.get("status") == "done":
        logs = await run_db(get_session_exercise_logs, today_session["id"])
        if logs:
            lines = []
            for log in logs:
                icon = "✅" if log["status"] == "done" else "⏭"
                name = log["exercise_name"]
                res = log.get("result")
                if res and isinstance(res, dict):
                    s = res.get("sets_done","?")
                    r = res.get("reps_done","?")
                    w = res.get("weight_done")
                    detail = f"{s}×{r}" + (f" @ {w}кг" if w else "")
                    lines.append(f"{icon} {name} — {detail}")
                else:
                    lines.append(f"{icon} {name}")
            today_str = "\nСегодня:\n" + "\n".join(lines)

    text = (
        f"🏋️ Тренировки\n\n"
        f"{today_wd}, {date_str}\n\n"
        f"Неделя: {week_bar}"
        + today_str
    )
    msg = await bot.send_message(chat_id, text, reply_markup=workout_main_keyboard())
    nav_push(user_id, "workout")
    temps = user_temp_messages.get(user_id, {})
    temps['workout_menu'] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(F.data == "menu_workouts")
async def handle_workouts(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    user_id = callback.from_user.id
    await state.clear()
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[user_id] = None
    # Sweep any leftover temp messages from an interrupted flow (add-workout,
    # AI plan wizard, skip-reason prompt, calorie entry, etc.) — every other
    # section entry point (handle_diet, back_to_main_msg, ...) already does this.
    await delete_temp_messages(bot, user_id, callback.message.chat.id, keep_ai=True)
    await show_workout_main_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



@router.message(WorkoutState.waiting_for_goal)
async def process_workout_goal(message: Message, bot: Bot, state: FSMContext):
    try:
        goal = int(message.text.strip())
        if not 1 <= goal <= 31:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число от 1 до 31!")
        return
    set_workout_goal(message.from_user.id, goal)
    await state.clear()
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(message.from_user.id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('workout_setup'))
    await send_main_menu(bot, message.from_user.id, message.chat.id)



async def _do_workout_add(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.pop('workout_menu', None))
    await delete_message_safe(bot, chat_id, temps.pop('tasks_menu', None))
    cursor = db.execute('SELECT id, name FROM exercise_categories WHERE user_id = ? ORDER BY name', (user_id,))
    categories = cursor.fetchall()
    await state.set_state(WorkoutState.choosing_category)
    msg = await bot.send_message(chat_id, "Выбери категорию упражнения:", reply_markup=workout_categories_keyboard(categories, action="add"))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id



@router.callback_query(F.data == "menu_workout_add")
async def workout_add_msg(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    user_id = callback.from_user.id
    await state.clear()
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        name = get_user_name(user_id, callback.from_user.first_name)
        msg = await callback.message.answer(
            f"{name}, план тренировок не настроен.\n\nСоздать план с ИИ или введёшь свой?",
            reply_markup=wp_mode_keyboard()
        )
        user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
        nav_push(user_id, "wp_mode")
    else:
        await show_ai_workout_today(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.callback_query(F.data == "workout_add")
async def workout_add_start(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await _do_workout_add(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.callback_query(F.data == "w_back_to_main_from_add")
async def workout_back_to_main(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await state.clear()
    # Отправляем в главное меню (не в меню тренировок!)
    await send_main_menu(bot, user_id, callback.message.chat.id)
    await callback.answer()



@router.callback_query(WorkoutState.choosing_category, F.data.startswith("w_add_cat_"))
async def workout_add_choose_category(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    if data.get('workout_charts_mode'):
        await workout_charts_choose_category(callback, bot, state)
        return
    cat_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', (user_id, cat_id))
    exercises = cursor.fetchall()
    await state.update_data(category_id=cat_id)
    await state.set_state(WorkoutState.choosing_exercise)
    msg = await callback.message.answer("Выбери упражнение:", reply_markup=workout_exercises_keyboard(exercises, cat_id, action="add"))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(WorkoutState.choosing_exercise, F.data.startswith("w_add_ex_"))
async def workout_add_choose_exercise(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    if data.get('workout_charts_mode'):
        await workout_charts_generate(callback, bot, state)
        return
    ex_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT name, category_id, target_sets, target_reps, target_weight, target_distance, target_duration, weight_increment FROM exercises WHERE id = ?', (ex_id,))
    row = cursor.fetchone()
    if not row:
        await callback.message.answer("❌ Упражнение не найдено.")
        await workout_add_start(callback, bot, state)
        await callback.answer()
        return
    ex_name, cat_id, t_sets, t_reps, t_weight, t_dist, t_dur, inc = row
    type_cursor = db.execute('SELECT ex_type FROM exercise_categories WHERE id = ?', (cat_id,))
    type_row = type_cursor.fetchone()
    ex_type = type_row[0] if type_row else 'strength'

    target_info = ""
    last_info = ""
    if ex_type == 'strength' and t_sets and t_reps:
        target_info = f"\n🎯 Текущая цель: {t_sets}х{t_reps}"
        if t_weight:
            target_info += f" с весом {t_weight} кг"
        if inc:
            target_info += f" (шаг +{inc} кг)"
    elif ex_type == 'cardio' and t_dist and t_dur:
        target_info = f"\n🎯 Текущая цель: {t_dist} км за {t_dur} мин"

    last_cursor = db.execute('''
        SELECT sets, reps, weight, distance, duration, date
        FROM workout_log
        WHERE user_id = ? AND exercise_name = ? AND category_id = ?
        ORDER BY date DESC LIMIT 1
    ''', (user_id, ex_name, cat_id))
    last_row = last_cursor.fetchone()
    if last_row:
        last_sets, last_reps, last_weight, last_dist, last_dur, last_date = last_row
        last_date_formatted = datetime.strptime(last_date, '%Y-%m-%d').strftime('%d.%m')
        if ex_type == 'strength' and last_sets is not None:
            last_info = f"\n📊 Прошлый раз: {last_sets}х{last_reps}"
            if last_weight:
                last_info += f" ({last_weight} кг)"
            last_info += f" ({last_date_formatted})"
        elif ex_type == 'cardio' and last_dist is not None:
            last_info = f"\n📊 Прошлый раз: {last_dist} км / {last_dur} мин ({last_date_formatted})"

    await state.update_data(
        exercise_id=ex_id, exercise_name=ex_name, category_id=cat_id, ex_type=ex_type,
        target_sets=t_sets, target_reps=t_reps, target_weight=t_weight,
        target_distance=t_dist, target_duration=t_dur, weight_increment=inc
    )

    text = f"Упражнение: {ex_name}" + target_info + last_info + "\n\nВыбери действие:"
    msg = await callback.message.answer(text, reply_markup=workout_action_choice_keyboard(ex_id))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data.startswith("w_manual_"))
async def workout_manual_enter(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    data = await state.get_data()
    ex_type = data.get('ex_type', 'strength')
    await callback.message.delete()
    if ex_type == 'cardio':
        await state.set_state(WorkoutState.entering_distance)
        msg = await callback.message.answer("Введи дистанцию в км (или отправь '-', если не хочешь указывать):",
                                             reply_markup=back_reply_keyboard())
    else:
        await state.set_state(WorkoutState.entering_reps)
        msg = await callback.message.answer("Введи повторения.\nПримеры: 10, 10,8,6 или 3x10",
                                             reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.message(WorkoutState.entering_reps)
async def workout_enter_reps(message: Message, bot: Bot, state: FSMContext):
    reps_input = message.text.strip()
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))

    data = await state.get_data()
    ex_type = data.get('ex_type', 'strength')

    if ex_type == 'strength':
        try:
            sets, reps_list = parse_reps_input(reps_input)
            reps_str = ','.join(str(r) for r in reps_list)
            await state.update_data(sets=sets, reps=reps_str)
            await state.set_state(WorkoutState.entering_weight)
            msg = await message.answer("Введи вес в кг (или отправь '-', если не хочешь указывать):",
                                       reply_markup=back_reply_keyboard())
        except ValueError:
            msg = await message.answer("❌ Неверный формат. Попробуй ещё раз (например, 10, 10,8,6 или 3x10):")
    else:
        try:
            parts = reps_input.split()
            if len(parts) == 2:
                distance = float(parts[0].replace(',', '.'))
                duration = int(parts[1])
                await state.update_data(distance=distance, duration=duration)
                await save_workout_and_continue(message, bot, state, user_id)
                return
        except:
            pass
        await state.update_data(distance=None, duration=None)
        await state.set_state(WorkoutState.entering_distance)
        msg = await message.answer("Введи дистанцию в км (или отправь '-', если не хочешь указывать):",
                                    reply_markup=back_reply_keyboard())

    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id



async def save_workout_and_continue(message: Message, bot: Bot, state: FSMContext, user_id: int):
    data = await state.get_data()
    ex_name = data['exercise_name']
    ex_type = data.get('ex_type', 'strength')
    today = user_today_str(user_id)

    if ex_type == 'strength':
        sets = data['sets']
        reps = data['reps']
        weight = data.get('weight')
        db.execute('''
            INSERT INTO workout_log (user_id, date, category_id, exercise_name, sets, reps, weight)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, today, data.get('category_id'), ex_name, sets, reps, weight))
        result_text = f"Сохранено: {ex_name} – {sets}х{reps}" + (f" ({weight} кг)" if weight else "")
    else:
        distance = data.get('distance')
        duration = data.get('duration')
        db.execute('''
            INSERT INTO workout_log (user_id, date, category_id, exercise_name, distance, duration)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, today, data.get('category_id'), ex_name, distance, duration))
        parts = []
        if distance:
            parts.append(f"{distance} км")
        if duration:
            parts.append(f"{duration} мин")
        result_text = f"Сохранено: {ex_name}" + (" – " + " / ".join(parts) if parts else "")
    db.commit()

    cursor = db.execute('SELECT COUNT(*) FROM workout_log WHERE user_id = ? AND date = ?', (user_id, today))
    count = cursor.fetchone()[0]

    spark_awarded = False
    if count == 1:
        add_workout(user_id)
        success, _, rank_up, old_rank, new_rank = add_spark(user_id, 'workout')
        if success:
            spark_awarded = True
            update_streak(user_id)
            if rank_up:
                await send_temp_message(bot, message.chat.id, f"✨ Новый ранг: {get_rank_name(new_rank)}!", delay=3)

    if spark_awarded:
        result_text += "\n✨ Искра за тренировку зачислена!"

    target_btn = None
    if data.get('target_sets') and data.get('target_reps'):
        target_sets = data['target_sets']
        target_reps = data['target_reps']
        target_weight = data.get('target_weight')
        sets = data.get('sets')
        reps = data.get('reps')
        if sets == target_sets and reps == target_reps:
            pass
        else:
            target_btn = InlineKeyboardButton(
                text=f"🎯 Цель: {target_sets}х{target_reps}" + (f" +{target_weight}кг" if target_weight else ""),
                callback_data=f"w_show_goal_{data['exercise_id']}"
            )
    elif data.get('target_distance') and data.get('target_duration'):
        target_dist = data['target_distance']
        target_dur = data['target_duration']
        distance = data.get('distance')
        duration = data.get('duration')
        if distance == target_dist and duration == target_dur:
            pass
        else:
            target_btn = InlineKeyboardButton(
                text=f"🎯 Цель: {target_dist}км / {target_dur}мин",
                callback_data=f"w_show_goal_{data['exercise_id']}"
            )

    markup = workout_continue_keyboard()
    if target_btn:
        markup.inline_keyboard.insert(0, [target_btn])

    await state.set_state(WorkoutState.confirm_continue)
    await message.answer(result_text, reply_markup=markup)



@router.message(WorkoutState.entering_weight)
async def workout_enter_weight(message: Message, bot: Bot, state: FSMContext):
    weight_str = message.text.strip()
    weight = None
    if weight_str != '-':
        try:
            weight = float(weight_str.replace(',', '.'))
        except ValueError:
            await message.answer("❌ Введи число или '-'.")
            return
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))
    await state.update_data(weight=weight)
    await save_workout_and_continue(message, bot, state, user_id)



@router.message(WorkoutState.entering_distance)
async def workout_enter_distance(message: Message, bot: Bot, state: FSMContext):
    dist_str = message.text.strip()
    distance = None
    if dist_str != '-':
        try:
            distance = float(dist_str.replace(',', '.'))
        except ValueError:
            await message.answer("❌ Введи число или '-'.")
            return
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))
    await state.update_data(distance=distance)
    await state.set_state(WorkoutState.entering_duration)
    msg = await message.answer("Введи время в минутах (или отправь '-', если не хочешь указывать):",
                                reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id



@router.message(WorkoutState.entering_duration)
async def workout_enter_duration(message: Message, bot: Bot, state: FSMContext):
    dur_str = message.text.strip()
    duration = None
    if dur_str != '-':
        try:
            duration = int(dur_str)
            if duration <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Введи положительное число или '-'.")
            return
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))
    await state.update_data(duration=duration)
    await save_workout_and_continue(message, bot, state, user_id)



@router.callback_query(F.data == "w_continue_yes", WorkoutState.confirm_continue)
async def workout_continue_yes(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await state.update_data(sets=None, reps=None, weight=None, distance=None, duration=None)
    cursor = db.execute('SELECT id, name FROM exercise_categories WHERE user_id = ? ORDER BY name', (user_id,))
    categories = cursor.fetchall()
    await state.set_state(WorkoutState.choosing_category)
    msg = await callback.message.answer("Выбери категорию упражнения:", reply_markup=workout_categories_keyboard(categories, action="add"))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data.startswith("w_achieve_goal_"))
async def workout_achieve_goal(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    cursor = db.execute('''
        SELECT e.name, e.category_id, e.target_sets, e.target_reps, e.target_weight, e.weight_increment,
               e.target_distance, e.target_duration, c.ex_type
        FROM exercises e
        LEFT JOIN exercise_categories c ON e.category_id = c.id
        WHERE e.id = ? AND e.user_id = ?
    ''', (ex_id, user_id))
    row = cursor.fetchone()
    if not row:
        await callback.answer("❌ Упражнение не найдено", show_alert=True)
        return
    ex_name, cat_id, target_sets, target_reps, target_weight, inc, target_distance, target_duration, ex_type = row
    today = user_today_str(user_id)

    # Проверяем ДО вставки для определения первой тренировки дня
    cursor = db.execute('SELECT COUNT(*) FROM workout_log WHERE user_id = ? AND date = ?', (user_id, today))
    count_before = cursor.fetchone()[0]

    # Сохраняем в workout_log
    if ex_type == 'strength':
        db.execute('''
            INSERT INTO workout_log (user_id, date, category_id, exercise_name, sets, reps, weight)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, today, cat_id, ex_name, target_sets, target_reps, target_weight))
        result_text = f"Сохранено: {ex_name} – {target_sets}х{target_reps}" + (f" ({target_weight} кг)" if target_weight else "")
    else:
        db.execute('''
            INSERT INTO workout_log (user_id, date, category_id, exercise_name, distance, duration)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, today, cat_id, ex_name, target_distance, target_duration))
        parts_list = []
        if target_distance:
            parts_list.append(f"{target_distance} км")
        if target_duration:
            parts_list.append(f"{target_duration} мин")
        result_text = f"Сохранено: {ex_name}" + (" – " + " / ".join(parts_list) if parts_list else "")
    db.commit()

    if count_before == 0:
        add_workout(user_id)
        success, _, rank_up, old_rank, new_rank = add_spark(user_id, 'workout')
        if success and rank_up:
            result_text += f"\n✨ Новый ранг: {get_rank_name(new_rank)}!"
        elif success:
            result_text += "\n✨ Искра за тренировку зачислена!"
    await callback.message.delete()
    markup = workout_continue_keyboard()
    await callback.message.answer(result_text, reply_markup=markup)
    await state.set_state(WorkoutState.confirm_continue)
    await state.update_data(sets=None, reps=None, weight=None, distance=None, duration=None)
    await callback.answer()



async def show_ai_workout_today(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    """Главный экран — план на сегодня или день отдыха."""
    try:
        await _show_ai_workout_today_inner(user_id, chat_id, bot, state)
    except Exception as e:
        import traceback
        print(f"[WORKOUT TODAY] Error: {e}")
        traceback.print_exc()
        temps = user_temp_messages.get(user_id, {})
        await delete_message_safe(bot, chat_id, temps.get('workout_menu'))
        msg = await bot.send_message(chat_id, "Произошла ошибка при загрузке плана. Попробуй ещё раз.",
                                      reply_markup=ws_rest_day_keyboard())
        user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id



async def _show_ai_workout_today_inner(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        return
    nav_push(user_id, "workout_today")

    today_exercises = get_today_plan(plan_data, user_id)
    temps = user_temp_messages.get(user_id, {})

    if not today_exercises:
        # День отдыха
        # Удаляем предыдущее сообщение workout_menu
        await delete_message_safe(bot, chat_id, temps.get('workout_menu'))
        
        next_date, next_day = get_next_training_day(plan_data, user_id)
        text = "Сегодня день отдыха."
        if next_date and next_day:
            text += f"\nСледующая тренировка: {next_day}, {next_date}"
        msg = await bot.send_message(chat_id, text, reply_markup=ws_rest_day_keyboard())
        temps['workout_menu'] = msg.message_id
        user_temp_messages[user_id] = temps
        return

    # Создаём сессию если нет
    session = create_today_session(user_id, plan_data)
    if session and session["status"] in ("done", "skipped"):
        # Уже завершили сегодня
        # Удаляем предыдущее сообщение workout_menu
        await delete_message_safe(bot, chat_id, temps.get('workout_menu'))
        
        text = "Сегодняшняя тренировка уже записана."
        next_date, next_day = get_next_training_day(plan_data, user_id)
        if next_date:
            text += f"\nСледующая: {next_day}, {next_date}"
        msg = await bot.send_message(chat_id, text, reply_markup=ws_rest_day_keyboard())
        temps['workout_menu'] = msg.message_id
        user_temp_messages[user_id] = temps
        return

    # Получаем историю прошлого раза
    weekday = user_weekday(user_id)
    today_key = WEEKDAY_KEY[weekday]
    week_key = get_current_week_session_key(plan_data, plan_data["start_date"], user_id)
    session_key = f"{week_key}_{today_key}"
    today_str = user_today_str(user_id)
    prev_sessions = get_previous_same_session(user_id, session_key, today_str)

    # Строим текст плана
    plan_name = f"Тренировка — {WEEKDAY_RU[weekday]}"
    date_str = user_today_str(user_id, '%d.%m.%Y')
    lines = [f"{plan_name}", f"{date_str}", ""]
    for i, ex in enumerate(today_exercises, 1):
        name = ex.get("exercise", ex.get("name", "?"))
        sets = ex.get("sets", "?")
        reps = ex.get("reps", "?")
        weight = ex.get("weight")
        line = f"{i}. {name}  {sets}×{reps}"
        if weight:
            line += f" @ {weight}кг"
        lines.append(line)

    # Добавляем важное из прошлого раза
    if prev_sessions:
        last = prev_sessions[0]
        last_logs = last.get("logs", [])
        last_date = datetime.strptime(last["date"], "%Y-%m-%d").strftime("%d.%m")
        important = []
        for log in last_logs:
            if log["status"] == "skipped":
                important.append(f"⏭ {log['exercise_name']} — пропущено")
            elif log.get("result") and log["result"].get("note"):
                important.append(f"⚠️ {log['exercise_name']} — {log['result']['note']}")
        if important:
            lines.append(f"\nПрошлый раз ({last_date}):")
            lines.extend(important)

    text = "\n".join(lines)
    await state.set_state(WorkoutSessionState.viewing_plan)
    await state.update_data(session_id=session["id"] if session else None,
                            exercise_index=0, prev_sessions=prev_sessions or [])
    msg = await bot.send_message(chat_id, text, reply_markup=ws_today_keyboard())
    temps['workout_menu'] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(F.data == "wp_mode_ai")
async def wp_choose_ai(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AIPlanState.choosing_goal)
    await callback.message.edit_text(
        "Создание плана тренировок\n\nШаг 1 из 3\nКакая твоя цель?",
        reply_markup=wp_goal_keyboard()
    )
    nav_push(callback.from_user.id, "wp_goal")
    await callback.answer()



@router.callback_query(F.data == "wp_mode_manual")
async def wp_choose_manual(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AIPlanState.entering_manual_plan)
    await callback.message.edit_text(
        "Отправь план одним сообщением в таком формате:\n\n"
        "День недели:\n"
        "Название упражнения - СетыxПовторения(Вес)\n\n"
        "Примеры строк:\n"
        "Жим лёжа - 3x5(110кг)\n"
        "Подтягивания - 3x10(+20кг)\n"
        "Становая тяга - МАХ(120кг)\n"
        "Отжимания - МАХ повторений(20кг)\n"
        "Присед - 2x(от 80кг к 60кг)\n"
        "Тренировка навыков - 40 минут\n\n"
        "Если в один день разные упражнения по неделям:\n"
        "Понедельник:\n"
        "Неделя 1 - Жим лёжа - МАХ(120кг)\n"
        "Неделя 2 - Жим лёжа - 3x5(110кг)\n"
        "Неделя 3 - Жим на наклонной - 3x11(90кг)\n"
        "Разгибания трицепса - 3x12(40кг)\n\n"
        "Упражнения без метки «Неделя N» дублируются во все недели.\n\n"
        "⚠️ Чем точнее формат — тем лучше ИИ разберёт план.",
        reply_markup=back_reply_keyboard()
    )
    nav_push(callback.from_user.id, "wp_manual")
    await callback.answer()



@router.callback_query(F.data == "wp_back_to_mode")
async def wp_back_to_mode(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AIPlanState.choosing_mode)
    name = get_user_name(callback.from_user.id, callback.from_user.first_name)
    await callback.message.edit_text(
        f"{name}, давай настроим тренировки!\n\nСоздать план с ИИ или введёшь свой?",
        reply_markup=wp_mode_keyboard()
    )
    nav_push(callback.from_user.id, "wp_mode")
    await callback.answer()



@router.callback_query(AIPlanState.choosing_goal, F.data.startswith("wp_goal_"))
async def wp_choose_goal(callback: CallbackQuery, bot: Bot, state: FSMContext):
    goal_map = {"wp_goal_mass": "Набор массы", "wp_goal_loss": "Похудение",
                "wp_goal_strength": "Сила", "wp_goal_fitness": "Общая форма"}
    goal = goal_map.get(callback.data, "Общая форма")
    await state.update_data(wp_goal=goal)
    await state.set_state(AIPlanState.choosing_level)
    await callback.message.edit_text(
        f"Создание плана тренировок\n\nШаг 2 из 3\nТвой уровень подготовки?",
        reply_markup=wp_level_keyboard()
    )
    nav_push(callback.from_user.id, "wp_level")
    await callback.answer()



@router.callback_query(F.data == "wp_back_to_goal")
async def wp_back_to_goal(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AIPlanState.choosing_goal)
    await callback.message.edit_text(
        "Создание плана тренировок\n\nШаг 1 из 3\nКакая твоя цель?",
        reply_markup=wp_goal_keyboard()
    )
    nav_push(callback.from_user.id, "wp_goal")
    await callback.answer()



@router.callback_query(AIPlanState.choosing_level, F.data.startswith("wp_level_"))
async def wp_choose_level(callback: CallbackQuery, bot: Bot, state: FSMContext):
    level_map = {"wp_level_beginner": "Новичок", "wp_level_intermediate": "Средний",
                 "wp_level_advanced": "Продвинутый"}
    level = level_map.get(callback.data, "Средний")
    await state.update_data(wp_level=level)
    await state.set_state(AIPlanState.choosing_days_count)
    await callback.message.edit_text(
        "Создание плана тренировок\n\nШаг 3 из 3\nСколько тренировок в неделю готов делать?",
        reply_markup=wp_days_keyboard()
    )
    nav_push(callback.from_user.id, "wp_days")
    await callback.answer()



@router.callback_query(F.data == "wp_back_to_level")
async def wp_back_to_level(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AIPlanState.choosing_level)
    await callback.message.edit_text(
        "Создание плана тренировок\n\nШаг 2 из 3\nТвой уровень подготовки?",
        reply_markup=wp_level_keyboard()
    )
    nav_push(callback.from_user.id, "wp_level")
    await callback.answer()



@router.callback_query(AIPlanState.choosing_days_count, F.data.startswith("wp_days_"))
async def wp_choose_days(callback: CallbackQuery, bot: Bot, state: FSMContext):
    days = int(callback.data.split("_")[2])
    data = await state.get_data()
    goal = data.get("wp_goal", "Общая форма")
    level = data.get("wp_level", "Средний")
    await state.update_data(wp_days=days)
    await state.set_state(AIPlanState.entering_extra_notes)
    await callback.message.edit_text(
        "Есть пожелания или особенности?\n\n"
        "Например: «травма колена», «нет штанги», «только утром»\n"
        "Или нажми Пропустить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb([
            [InlineKeyboardButton(text="Пропустить →", callback_data="wp_notes_skip")]
        ]))
    )
    nav_push(callback.from_user.id, "wp_notes")
    await callback.answer()



@router.callback_query(AIPlanState.entering_extra_notes, F.data == "wp_notes_skip")
async def wp_notes_skip(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.update_data(wp_notes="")
    await _generate_and_show_plan(callback, bot, state)
    await callback.answer()



@router.message(AIPlanState.entering_extra_notes)
async def wp_notes_input(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    try:
        await message.delete()
    except:
        pass
    await state.update_data(wp_notes=message.text.strip())
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    class FakeCB:
        def __init__(self):
            self.from_user = message.from_user
            self.message = type("M", (), {
                "chat": message.chat,
                "message_id": msg_id,
                "edit_text": lambda text, **kw: bot.edit_message_text(text, message.chat.id, msg_id, **kw),
            })()
        async def answer(self): pass
    await _generate_and_show_plan(FakeCB(), bot, state)



async def _generate_and_show_plan(callback, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    goal = data.get("wp_goal", "Общая форма")
    level = data.get("wp_level", "Средний")
    days = data.get("wp_days", 3)
    notes = data.get("wp_notes", "")
    await state.set_state(AIPlanState.reviewing_plan)
    # Start animation
    phrases = ["Анализирую...", "Ищу пишущую ручку...", "Составляю программу...",
               "Подбираю упражнения...", "Рассчитываю нагрузку...", "Финальные штрихи..."]
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    stop_animation = asyncio.Event()
    async def animate():
        i = 0
        while not stop_animation.is_set():
            try:
                await bot.edit_message_text(phrases[i % len(phrases)],
                                             callback.message.chat.id, msg_id)
            except:
                pass
            await asyncio.sleep(2)
            i += 1
    anim_task = asyncio.create_task(animate())
    try:
        plan = await run_in_thread(gemini_generate_plan, goal, level, days, notes)
    finally:
        stop_animation.set()
        anim_task.cancel()
        try:
            await anim_task
        except asyncio.CancelledError:
            pass
    if not plan:
        try:
            await bot.edit_message_text(
                "Не удалось сгенерировать план. Попробуй ещё раз.",
                callback.message.chat.id, msg_id,
                reply_markup=retry_ai_keyboard("generate_plan")
            )
        except:
            pass
        return
    await state.update_data(wp_plan=plan, retry_action="generate_plan")
    text = _format_full_plan(plan, goal, level, days)
    try:
        await bot.edit_message_text(text, callback.message.chat.id, msg_id,
                                     reply_markup=wp_plan_review_keyboard())
    except:
        msg = await bot.send_message(callback.message.chat.id, text,
                                      reply_markup=wp_plan_review_keyboard())
        user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
    nav_push(user_id, "wp_review")



@router.callback_query(F.data == "wp_back_to_days")
async def wp_back_to_days(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AIPlanState.choosing_days_count)
    await callback.message.edit_text(
        "Создание плана тренировок\n\nШаг 3 из 3\nСколько тренировок в неделю?",
        reply_markup=wp_days_keyboard()
    )
    nav_push(callback.from_user.id, "wp_days")
    await callback.answer()



@router.callback_query(F.data == "wp_plan_regenerate")
async def wp_regenerate(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    goal = data.get("wp_goal", "Общая форма")
    level = data.get("wp_level", "Средний")
    days = data.get("wp_days", 3)
    await _generate_and_show_plan(callback, bot, state)
    await callback.answer()



@router.callback_query(F.data == "wp_plan_edit")
async def wp_plan_edit_start(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(AIPlanState.editing_plan)
    await callback.message.edit_text(
        "Что хочешь изменить в плане?\n\nНапиши например:\n"
        "«убери приседания, замени на жим ногами»\n"
        "«добавь кардио в пятницу»",
        reply_markup=back_reply_keyboard()
    )
    nav_push(callback.from_user.id, "wp_edit")
    await callback.answer()



@router.callback_query(F.data == "wp_back_to_review")
async def wp_back_to_review(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    plan = data.get("wp_plan")
    goal = data.get("wp_goal", "")
    level = data.get("wp_level", "")
    days = data.get("wp_days", 3)
    if not plan:
        await callback.answer("Нет плана", show_alert=True)
        return
    await state.set_state(AIPlanState.reviewing_plan)
    text = _format_full_plan(plan, goal, level, days)
    await callback.message.edit_text(text, reply_markup=wp_plan_review_keyboard())
    nav_push(callback.from_user.id, "wp_review")
    await callback.answer()



async def _handle_exercise_replace(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    try:
        await message.delete()
    except:
        pass
    data = await state.get_data()
    ex_idx = data.get("wp_edit_ex_idx", 0)
    day_key = data.get("wp_edit_day", "monday")
    old_name = data.get("wp_edit_ex_name", "?")
    new_name = message.text.strip()
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        return
    plan = plan_data.get("plan", {})
    cycle = plan_data.get("cycle_weeks", 1)
    # Replace in all weeks that have this day
    for w in range(1, cycle + 1):
        week_key = f"week_{w}"
        if week_key in plan and day_key in plan[week_key]:
            exs = plan[week_key][day_key]
            if ex_idx < len(exs):
                exs[ex_idx]["exercise"] = new_name
    update_plan_json(user_id, plan)
    await state.clear()
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    confirm = f"Заменено: «{old_name}» → «{new_name}»"
    if msg_id:
        try:
            await bot.edit_message_text(confirm, message.chat.id, msg_id)
            return
        except:
            pass
    msg = await message.answer(confirm)
    user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
    nav_push(user_id, "workout_manage")



@router.message(AIPlanState.editing_plan)
async def wp_plan_edit_input(message: Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    # Route based on edit mode
    if data.get("wp_edit_mode") == "exercise_replace":
        await _handle_exercise_replace(message, bot, state)
        return
    # Original plan editing logic below

    user_id = message.from_user.id
    try:
        await message.delete()
    except:
        pass
    data = await state.get_data()
    current_plan = data.get("wp_plan")
    temps = user_temp_messages.get(user_id, {})
    edit_msg_id = temps.get("workout_menu")
    stop_upd = asyncio.Event()
    async def animate_upd():
        dots = ["Обновляю план.", "Обновляю план..", "Обновляю план..."]
        i = 0
        while not stop_upd.is_set():
            if edit_msg_id:
                try:
                    await bot.edit_message_text(dots[i % 3], message.chat.id, edit_msg_id)
                except:
                    pass
            await asyncio.sleep(0.8)
            i += 1
    anim_upd = asyncio.create_task(animate_upd())
    try:
        new_plan = await run_in_thread(gemini_edit_plan, current_plan, message.text.strip())
    finally:
        stop_upd.set()
        anim_upd.cancel()
        try:
            await anim_upd
        except asyncio.CancelledError:
            pass
    if not new_plan:
        back_to_workout_kb = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="wp_edit_retry")]
        ]))
        try:
            await bot.edit_message_text(
                "Не удалось применить изменения. Попробуй сформулировать иначе.",
                message.chat.id, edit_msg_id, reply_markup=back_to_workout_kb
            )
        except:
            pass
        nav_push(message.from_user.id, "wp_edit")
        return
    await state.update_data(wp_plan=new_plan)
    await state.set_state(AIPlanState.reviewing_plan)
    goal = data.get("wp_goal", "")
    level = data.get("wp_level", "")
    days = data.get("wp_days", 3)
    text = _format_full_plan(new_plan, goal, level, days)
    try:
        await bot.edit_message_text(text, message.chat.id, edit_msg_id,
                                     reply_markup=wp_plan_review_keyboard())
    except:
        pass



@router.callback_query(F.data == "wp_plan_accept")
async def wp_plan_accept(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    plan = data.get("wp_plan")
    if not plan:
        await callback.answer("План не найден. Попробуй сгенерировать заново.", show_alert=True)
        return
    mode = data.get("wp_mode", "ai" if data.get("wp_goal") else "manual")
    goal = data.get("wp_goal", "")
    level = data.get("wp_level", "")
    days = data.get("wp_days", 3)
    cycle_weeks = plan.get("cycle_weeks", 1) if isinstance(plan, dict) else 1
    # Удаляем все старые данные
    delete_all_workout_data(user_id)
    save_ai_plan(user_id, mode, goal, level, days, plan, cycle_weeks)
    await state.clear()
    # Мастер создания плана пройден — выкидываем его шаги из стека навигации
    stack = user_nav.get(user_id) or []
    user_nav[user_id] = [s for s in stack if not s.startswith("wp_")]
    # Показываем сообщение о сохранении и удаляем его через 2 секунды
    await callback.message.edit_text("✅ План сохранён! Возвращайся когда будешь готов тренироваться.")
    await asyncio.sleep(2)
    await callback.message.delete()
    await show_ai_workout_today(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.message(AIPlanState.entering_manual_plan)
async def wp_manual_input(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    raw_text = message.text.strip()
    print(f"[MANUAL INPUT] User {user_id} sent plan: {repr(raw_text[:200])}")
    try:
        await message.delete()
    except:
        pass
    # Сохраняем текст для повтора по кнопке
    await state.update_data(retry_manual_plan_text=raw_text, retry_action="manual_plan")
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    print(f"[MANUAL INPUT] msg_id={msg_id}")
    stop_anim = asyncio.Event()
    phrases_m = ["Читаю план...", "Разбираю структуру...", "Определяю дни...",
                 "Считаю подходы...", "Почти готово..."]
    async def animate_m():
        i = 0
        while not stop_anim.is_set():
            if msg_id:
                try:
                    await bot.edit_message_text(phrases_m[i % len(phrases_m)], message.chat.id, msg_id)
                except:
                    pass
            await asyncio.sleep(2)
            i += 1
    anim_m = asyncio.create_task(animate_m())
    try:
        plan = await run_in_thread(gemini_parse_manual_plan, raw_text)
    finally:
        stop_anim.set()
        anim_m.cancel()
        try:
            await anim_m
        except asyncio.CancelledError:
            pass
    
    print(f"[MANUAL INPUT] Parsing result: {'OK' if plan else 'FAILED'}")
    
    if not plan:
        print(f"[MANUAL INPUT] Trying fallback parser...")
        # Always try to generate something - ask ИИ to do best effort
        plan = await run_in_thread(_fallback_parse_plan, raw_text)
        print(f"[MANUAL INPUT] Fallback result: {'OK' if plan else 'FAILED'}")
    
    if not plan:
        print(f"[MANUAL INPUT] Both parsers failed, showing error to user")
        # Удаляем анимационное сообщение
        if msg_id:
            await delete_message_safe(bot, message.chat.id, msg_id)
        try:
            err_msg = await message.answer(
                "❌ Не смог разобрать план. Можно скинуть тот же текст — я попробую снова.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb([
                    [InlineKeyboardButton(text="🔄 Попробовать снова",
                                          callback_data="retry_ai:manual_plan")]
                ]))
            )
            user_temp_messages.setdefault(user_id, {})['workout_error'] = err_msg.message_id
        except Exception as e:
            print(f"[MANUAL INPUT] Error sending error message: {e}")
        return
    
    print(f"[MANUAL INPUT] Plan parsed successfully, cycle_weeks={plan.get('cycle_weeks')}")
    await state.update_data(wp_plan=plan, wp_mode="manual",
                            wp_goal="", wp_level="", wp_days=0)
    await state.set_state(AIPlanState.reviewing_plan)
    text = _format_full_plan(plan, "", "", 0)
    print(f"[MANUAL INPUT] Formatted plan text ({len(text)} chars): {text[:500]}")
    
    # Пробуем отредактировать существующее сообщение или отправить новое
    if msg_id:
        try:
            await bot.edit_message_text(text, message.chat.id, msg_id,
                                         reply_markup=wp_plan_review_keyboard_manual())
            print(f"[MANUAL INPUT] Successfully edited message {msg_id}")
        except Exception as e:
            print(f"[MANUAL INPUT] Edit failed ({type(e).__name__}: {e}), sending new message")
            # Если не удалось отредактировать - отправляем новое сообщение
            new_msg = await message.answer(text, reply_markup=wp_plan_review_keyboard_manual())
            # Обновляем msg_id в temp messages
            temps['workout_menu'] = new_msg.message_id
            user_temp_messages[user_id] = temps
    else:
        print(f"[MANUAL INPUT] No msg_id, sending new message")
        new_msg = await message.answer(text, reply_markup=wp_plan_review_keyboard_manual())
        temps = user_temp_messages.setdefault(user_id, {})
        temps['workout_menu'] = new_msg.message_id



@router.callback_query(F.data == "workout_main_ai")
async def workout_main_ai_callback(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await state.clear()
    try:
        await callback.message.delete()
    except:
        pass
    await show_ai_workout_today(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.callback_query(F.data == "back_to_workout_main")
async def back_to_workout_main_callback(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await state.clear()
    try:
        await callback.message.delete()
    except:
        pass
    await show_workout_main_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



async def _ws_start_workout(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    session_id = data.get("session_id")
    plan_data = get_ai_plan(user_id)
    session = get_today_session(user_id)
    if not session:
        try:
            await callback.answer("Сессия не найдена", show_alert=True)
        except:
            pass
        return
    exercises = session["plan"]
    if isinstance(exercises, dict):
        exercises = list(exercises.values())
    await state.update_data(exercises=exercises, exercise_index=0,
                            session_id=session["id"])
    await state.set_state(WorkoutSessionState.in_exercise)
    await _show_exercise(callback.message, bot, state, user_id, 0, exercises)



async def _show_exercise(message, bot: Bot, state: FSMContext,
                          user_id: int, index: int, exercises: list):
    """Редактирует сообщение показывая текущее упражнение."""
    ex = exercises[index]
    total = len(exercises)
    name = ex.get("exercise", ex.get("name", "?"))
    sets = ex.get("sets", "?")
    reps = ex.get("reps", "?")
    weight = ex.get("weight")

    # Ищем результат предыдущего раза
    data = await state.get_data()
    prev_sessions = data.get("prev_sessions", [])
    prev_result = None
    if prev_sessions:
        last_logs = prev_sessions[0].get("logs", [])
        for log in last_logs:
            if log.get("exercise_name") == name and log.get("result"):
                prev_result = log["result"]
                break

    text = f"Упражнение {index + 1} из {total}\n\n"
    text += f"{name}\n"
    text += f"Цель: {sets} подхода × {reps} повторений"
    if weight:
        text += f" @ {weight} кг"
    if prev_result:
        text += "\n\nПрошлый раз: "
        if prev_result.get("sets_done"):
            text += f"{prev_result['sets_done']}×{prev_result.get('reps_done','?')}"
        if prev_result.get("weight_done"):
            text += f" @ {prev_result['weight_done']} кг"
        if prev_result.get("note"):
            text += f" ({prev_result['note']})"
    text += "\n\nНапиши что сделал или нажми кнопку:"

    await state.set_state(WorkoutSessionState.in_exercise)
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    if msg_id:
        try:
            await bot.edit_message_text(text, message.chat.id, msg_id,
                                         reply_markup=ws_exercise_keyboard(is_first=(index == 0)))
            return
        except:
            pass
    msg = await message.answer(text, reply_markup=ws_exercise_keyboard(is_first=(index == 0)))
    temps["workout_menu"] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(WorkoutSessionState.in_exercise, F.data == "ws_ex_done")
async def ws_exercise_done(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    exercises = data.get("exercises", [])
    index = data.get("exercise_index", 0)
    session_id = data.get("session_id")
    ex = exercises[index]
    # Записываем как выполнено по плану
    result = {"sets_done": ex.get("sets"), "reps_done": ex.get("reps"),
               "weight_done": ex.get("weight"), "completed": True, "note": None}
    db.execute("""
        INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, result_json, status)
        VALUES (?, ?, ?, ?, ?, 'done')
    """, (session_id, user_id, ex.get("exercise", ex.get("name")),
           json.dumps(ex, ensure_ascii=False), json.dumps(result, ensure_ascii=False)))
    db.commit()
    await state.update_data(exercise_index=index + 1)
    await _next_exercise_or_finish(callback, bot, state, user_id)
    await callback.answer()



@router.callback_query(WorkoutSessionState.in_exercise, F.data == "ws_ex_skip")
async def ws_exercise_skip(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    exercises = data.get("exercises", [])
    index = data.get("exercise_index", 0)
    session_id = data.get("session_id")
    ex = exercises[index]
    db.execute("""
        INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, status)
        VALUES (?, ?, ?, ?, 'skipped')
    """, (session_id, user_id, ex.get("exercise", ex.get("name")),
           json.dumps(ex, ensure_ascii=False)))
    db.commit()
    await state.update_data(exercise_index=index + 1)
    await _next_exercise_or_finish(callback, bot, state, user_id)
    await callback.answer()



@router.callback_query(WorkoutSessionState.in_exercise, F.data == "ws_ex_prev")
async def ws_exercise_prev(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    index = data.get("exercise_index", 0)
    session_id = data.get("session_id")
    if index <= 0:
        await callback.answer("Это первое упражнение", show_alert=True)
        return
    # Удаляем последний лог
    db.execute("""
        DELETE FROM ai_exercise_logs WHERE session_id = ? AND user_id = ?
        AND id = (SELECT MAX(id) FROM ai_exercise_logs WHERE session_id = ? AND user_id = ?)
    """, (session_id, user_id, session_id, user_id))
    db.commit()
    new_index = index - 1
    await state.update_data(exercise_index=new_index)
    exercises = data.get("exercises", [])
    await _show_exercise(callback.message, bot, state, user_id, new_index, exercises)
    await callback.answer()



@router.message(WorkoutSessionState.in_exercise)
async def ws_exercise_text_input(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    try:
        await message.delete()
    except:
        pass
    data = await state.get_data()
    exercises = data.get("exercises", [])
    index = data.get("exercise_index", 0)
    session_id = data.get("session_id")
    ex = exercises[index]
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    if msg_id:
        try:
            await bot.edit_message_text("Записываю...", message.chat.id, msg_id)
        except:
            pass
    result = await run_in_thread(gemini_parse_exercise_result, ex, message.text.strip())
    db.execute("""
        INSERT INTO ai_exercise_logs
        (session_id, user_id, exercise_name, planned_json, raw_input, result_json, status)
        VALUES (?, ?, ?, ?, ?, ?, 'done')
    """, (session_id, user_id, ex.get("exercise", ex.get("name")),
           json.dumps(ex, ensure_ascii=False), message.text.strip(),
           json.dumps(result, ensure_ascii=False)))
    db.commit()
    await state.update_data(exercise_index=index + 1)
    # Передаём message для edit через фейк
    class FakeCallback:
        def __init__(self, msg, uid):
            self.message = msg
            self.from_user = type("U", (), {"id": uid})()
        async def answer(self): pass
    fake = FakeCallback(message, user_id)
    await _next_exercise_or_finish(fake, bot, state, user_id)



async def _next_exercise_or_finish(callback, bot: Bot, state: FSMContext, user_id: int):
    data = await state.get_data()
    exercises = data.get("exercises", [])
    index = data.get("exercise_index", 0)
    if index < len(exercises):
        await _show_exercise(callback.message, bot, state, user_id, index, exercises)
    else:
        await _finish_workout(callback.message, bot, state, user_id)



async def _finish_workout(message, bot: Bot, state: FSMContext, user_id: int):
    data = await state.get_data()
    session_id = data.get("session_id")
    exercises = data.get("exercises", [])
    today = user_today_str(user_id)

    # Помечаем сессию как выполненную
    db.execute("UPDATE ai_workout_sessions SET status='done', completed_at=? WHERE id=?",
               (today, session_id))
    db.commit()

    logs = get_session_exercise_logs(session_id)
    done = [l for l in logs if l["status"] == "done"]
    skipped = [l for l in logs if l["status"] == "skipped"]

    # Фидбек от ИИ
    feedback = await run_in_thread(gemini_session_feedback, logs, exercises)

    # Адаптируем план
    prev_sessions = data.get("prev_sessions", [])
    adapted = await run_in_thread(gemini_adapt_next_session, exercises, logs, prev_sessions)
    if adapted != exercises:
        session = get_today_session(user_id)
        if session:
            update_session_exercise_plan(user_id, session_id,
                                          session.get("session_key", ""), adapted)

    # Обновляем счётчик тренировок
    add_workout(user_id)
    success, _, rank_up, _, new_rank = add_spark(user_id, "workout")
    update_streak(user_id)
    asyncio.create_task(run_in_thread(sync_activity_rating_for_today, user_id))

    # Строим итоговое сообщение
    lines = ["Тренировка завершена\n"]
    for log in logs:
        if log["status"] == "skipped":
            lines.append(f"⏭ {log['exercise_name']} — пропущено")
        elif log.get("result") and log["result"].get("note"):
            lines.append(f"⚠️ {log['exercise_name']} — {log['result']['note']}")

    feedback_failed = feedback.startswith("❌")
    if feedback_failed:
        lines.append("\n❌ ИИ не смог подготовить фидбек.")
    else:
        lines.append(f"\n{feedback}")

    plan_data = get_ai_plan(user_id)
    next_date, next_day = get_next_training_day(plan_data, user_id) if plan_data else (None, None)
    if next_date:
        lines.append(f"\nСледующая тренировка: {next_day}, {next_date}")
    if rank_up:
        lines.append(f"\n✨ Новый ранг: {get_rank_name(new_rank)}!")

    text = "\n".join(lines)
    # Кнопка повтора фидбека (без ретипинга) — данные сессии уже сохранены
    finish_kb = retry_ai_keyboard("session_feedback") if feedback_failed else ws_rest_day_keyboard()
    await state.clear()
    # Сохраняем после clear() — данные нужны для повтора фидбека
    await state.update_data(retry_session_id=session_id,
                            retry_session_exercises=exercises)
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    if msg_id:
        try:
            await bot.edit_message_text(text, message.chat.id, msg_id,
                                         reply_markup=finish_kb)
            return
        except:
            pass
    msg = await message.answer(text, reply_markup=finish_kb)
    temps["workout_menu"] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(F.data == "ws_skip_day")
async def ws_skip_day_start(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(WorkoutSessionState.skipping_day)
    temps = user_temp_messages.get(callback.from_user.id, {})
    msg_id = temps.get("workout_menu")
    text = "Почему пропускаешь тренировку? Напиши кратко (или просто отправь «-»):"
    if msg_id:
        try:
            await callback.message.edit_text(text, reply_markup=ws_skip_day_keyboard())
            await callback.answer()
            return
        except:
            pass
    msg = await callback.message.answer(text, reply_markup=ws_skip_day_keyboard())
    temps["workout_menu"] = msg.message_id
    user_temp_messages[callback.from_user.id] = temps
    await callback.answer()



@router.callback_query(WorkoutSessionState.skipping_day, F.data == "ws_back_to_today")
async def ws_back_to_today(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    try:
        await callback.message.delete()
    except:
        pass
    temps = user_temp_messages.get(user_id, {})
    temps.pop("workout_menu", None)
    user_temp_messages[user_id] = temps
    await show_ai_workout_today(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.message(WorkoutSessionState.skipping_day)
async def ws_skip_day_reason(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    reason = message.text.strip() if message.text.strip() != "-" else ""
    try:
        await message.delete()
    except:
        pass
    plan_data = get_ai_plan(user_id)
    if plan_data:
        session = create_today_session(user_id, plan_data)
        if session:
            db.execute("""
                UPDATE ai_workout_sessions SET status='skipped', skip_reason=? WHERE id=?
            """, (reason, session["id"]))
            db.commit()
    await state.clear()
    # Отнимаем искру за пропущенный тренировочный день
    _deduct_spark_for_skip(user_id)
    temps = user_temp_messages.get(user_id, {})
    msg_id = temps.get("workout_menu")
    text = "День пропущен."
    plan_data = get_ai_plan(user_id)
    next_date, next_day = get_next_training_day(plan_data, user_id) if plan_data else (None, None)
    if next_date:
        text += f"\nСледующая тренировка: {next_day}, {next_date}"
    if msg_id:
        try:
            await bot.edit_message_text(text, message.chat.id, msg_id,
                                         reply_markup=ws_rest_day_keyboard())
            return
        except:
            pass
    msg = await message.answer(text, reply_markup=ws_rest_day_keyboard())
    temps["workout_menu"] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(F.data == "wp_settings")
async def wp_settings(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.edit_text("Настройки плана тренировок:",
                                      reply_markup=wp_settings_keyboard())
    await callback.answer()



@router.callback_query(F.data == "wp_reset")
async def wp_reset(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    delete_all_workout_data(user_id)
    await state.clear()
    name = get_user_name(user_id, callback.from_user.first_name)
    await callback.message.edit_text(
        f"{name}, давай настроим тренировки!\n\nСоздать план с ИИ или введёшь свой?",
        reply_markup=wp_mode_keyboard()
    )
    await callback.answer()



@router.callback_query(F.data == "wp_monthly_review")
async def wp_monthly_review_start(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.edit_text("Анализирую прогресс...")
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        await callback.answer("Нет плана", show_alert=True)
        return
    cursor = db.execute("""
        SELECT date, plan_json, status FROM ai_workout_sessions
        WHERE user_id = ? ORDER BY date DESC LIMIT 20
    """, (user_id,))
    recent = []
    for row in cursor.fetchall():
        recent.append({"date": row[0], "status": row[2]})
    await state.update_data(retry_action="monthly_review")
    changes = await run_in_thread(gemini_monthly_review, plan_data["plan"], recent)
    if not changes:
        # Реальная ошибка ИИ — предлагаем повторить (не путать с «менять не нужно»)
        await callback.message.edit_text(
            "❌ Не удалось проанализировать прогресс.\n\n"
            "🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("monthly_review")
        )
        await callback.answer()
        return
    if changes.get("no_changes_needed") or not changes.get("changes"):
        await callback.message.edit_text(
            "Менять ничего не нужно — план хорошо сбалансирован.",
            reply_markup=wp_settings_keyboard()
        )
        await callback.answer()
        return
    chg = changes["changes"]
    await state.set_state(WorkoutSessionState.monthly_review)
    await state.update_data(review_changes=chg)
    lines = ["Предлагаю заменить упражнения:\n"]
    for i, ch in enumerate(chg, 1):
        lines.append(f"{i}. {ch['old_exercise']} → {ch['new_exercise']}\n   {ch['reason']}")
    lines.append("\nНапиши номера изменений которые принять (например: 1 3) или «нет» чтобы отклонить всё:")
    await callback.message.edit_text("\n".join(lines))
    nav_push(callback.from_user.id, "wp_review_decline_prompt")
    await callback.answer()



@router.message(WorkoutSessionState.monthly_review)
async def wp_monthly_review_input(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    try:
        await message.delete()
    except:
        pass
    data = await state.get_data()
    changes = data.get("review_changes", [])
    text = message.text.strip().lower()
    if text in ("нет", "no", "-"):
        await state.clear()
        await bot.send_message(message.chat.id, "Изменения отклонены. План остаётся прежним.",
                                reply_markup=wp_settings_keyboard())
        return
    try:
        indices = [int(x) - 1 for x in text.split() if x.isdigit()]
    except:
        indices = []
    if not indices:
        await bot.send_message(message.chat.id,
                                "Не понял. Напиши номера через пробел или «нет».")
        return
    plan_data = get_ai_plan(user_id)
    if plan_data:
        new_plan = apply_monthly_changes(user_id, plan_data, indices, changes)
        update_plan_json(user_id, new_plan)
        today = user_today_str(user_id)
        db.execute("UPDATE ai_workout_plan SET last_monthly_review=? WHERE user_id=?",
                   (today, user_id))
        db.commit()
    await state.clear()
    accepted = [changes[i]["old_exercise"] + " → " + changes[i]["new_exercise"]
                for i in indices if i < len(changes)]
    await bot.send_message(message.chat.id,
                            f"Принято: {', '.join(accepted)}\nПлан обновлён.",
                            reply_markup=wp_settings_keyboard())



@router.callback_query(F.data == "wp_review_decline")
async def wp_review_decline(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Изменения отклонены.",
                                      reply_markup=wp_settings_keyboard())
    await callback.answer()



async def _do_workout_manage(user_id: int, chat_id: int, bot: Bot):
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.get('workout_menu'))
    if 'workout_menu' in temps:
        del temps['workout_menu']
    cursor = db.execute('SELECT id, name FROM exercise_categories WHERE user_id = ? ORDER BY name', (user_id,))
    categories = cursor.fetchall()
    msg = await bot.send_message(chat_id, "📋 Мои категории:", reply_markup=workout_categories_keyboard(categories, action="manage"))
    nav_push(user_id, "categories")
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id



async def _show_workout_manage_menu(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    """Экран «📋 Управление» (настройки плана). Родитель — меню тренировок."""
    nav_push(user_id, "workout_manage")
    plan_data = get_ai_plan(user_id)
    mode = plan_data.get("mode", "ai") if plan_data else "ai"
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.pop('workout_menu', None))
    user_temp_messages[user_id] = temps
    msg = await bot.send_message(chat_id, "Управление планом:", reply_markup=workout_manage_reply_keyboard(mode))
    user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id



@router.callback_query(F.data == "menu_workout_manage")
async def workout_manage_msg(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        await callback.message.delete()
        await callback.message.answer("План не настроен. Зайди в «🏋️ Добавить выполнение» чтобы создать.",
                                      reply_markup=workout_main_keyboard())
        nav_push(user_id, "workout")
        await callback.answer()
        return
    await callback.message.delete()
    await _show_workout_manage_menu(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.callback_query(F.data == "wp_edit_plan")
async def workout_edit_plan_msg(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    user_id = callback.from_user.id
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        await callback.answer()
        return
    await state.set_state(AIPlanState.editing_plan)
    await state.update_data(wp_plan=plan_data["plan"], wp_goal=plan_data.get("goal",""),
                            wp_level=plan_data.get("level",""), wp_days=plan_data.get("days_per_week",3))
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.pop('workout_menu', None))
    msg = await callback.message.answer(
        "Что изменить в плане?\n\nНапример:\n«убери приседания, замени на жим ногами»\n«добавь кардио в пятницу»",
        reply_markup=back_reply_keyboard()
    )
    user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
    nav_push(user_id, "wp_edit")
    await callback.answer()



@router.callback_query(F.data == "wp_new_plan")
async def workout_new_ai_plan_msg(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    user_id = callback.from_user.id
    name = get_user_name(user_id, callback.from_user.first_name)
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.pop('workout_menu', None))
    await state.set_state(AIPlanState.choosing_goal)
    msg = await callback.message.answer(
        f"{name}, создаём новый план с нуля.\n\nШаг 1 из 3\nКакая твоя цель?",
        reply_markup=wp_goal_keyboard()
    )
    user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
    nav_push(user_id, "wp_goal")
    await callback.answer()



@router.callback_query(F.data == "workout_manage_back")
async def workout_manage_back_cb(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    try:
        await callback.message.delete()
    except:
        pass
    await show_workout_main_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(F.data == "workout_manage")
async def workout_manage(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await _do_workout_manage(user_id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(F.data == "workout_main")
async def workout_main_callback(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await show_workout_main_menu(callback.from_user.id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(F.data == "w_cat_new")
async def workout_new_category(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await state.set_state(WorkoutState.creating_category)
    msg = await callback.message.answer(
        "Введи название новой категории (например, 'Грудь', 'Кардио'):",
        reply_markup=back_reply_keyboard()
    )
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.message(WorkoutState.creating_category)
async def workout_create_category(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    cat_name = message.text.strip()
    if len(cat_name) < 2:
        await message.answer("❌ Слишком короткое название. Попробуй ещё раз:")
        return
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))
    await state.update_data(new_cat_name=cat_name)
    msg = await message.answer(
        f"Тип категории «{cat_name}»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb([
            [InlineKeyboardButton(text="💪 Силовая", callback_data="cat_type_strength")],
            [InlineKeyboardButton(text="🚴 Кардио", callback_data="cat_type_cardio")],
        ]))
    )
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id



@router.callback_query(F.data.in_({"cat_type_strength", "cat_type_cardio"}))
async def workout_create_category_type(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    ex_type = 'strength' if callback.data == 'cat_type_strength' else 'cardio'
    data = await state.get_data()
    cat_name = data.get('new_cat_name', '').strip()
    await state.clear()
    await callback.message.delete()
    if not cat_name:
        await workout_manage_after_action(user_id, callback.message.chat.id, bot)
        await callback.answer()
        return
    try:
        db.execute('INSERT INTO exercise_categories (user_id, name, ex_type) VALUES (?, ?, ?)', (user_id, cat_name, ex_type))
        db.commit()
    except sqlite3.IntegrityError:
        await callback.answer("❌ Такая категория уже существует.", show_alert=True)
    await workout_manage_after_action(user_id, callback.message.chat.id, bot)
    await callback.answer()



async def workout_manage_after_action(user_id: int, chat_id: int, bot: Bot):
    temps = user_temp_messages.get(user_id, {})
    old = temps.pop('workout_temp', None)
    if old:
        await delete_message_safe(bot, chat_id, old)
    cursor = db.execute('SELECT id, name FROM exercise_categories WHERE user_id = ? ORDER BY name', (user_id,))
    categories = cursor.fetchall()
    msg = await bot.send_message(chat_id, "📋 Мои категории:", reply_markup=workout_categories_keyboard(categories, action="manage"))
    nav_push(user_id, "categories")
    temps['workout_temp'] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(F.data.startswith("w_manage_cat_"))
async def workout_manage_view_category(callback: CallbackQuery, bot: Bot, state: FSMContext):
    cat_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT name FROM exercise_categories WHERE id = ?', (cat_id,))
    row = cursor.fetchone()
    if not row:
        await callback.message.answer("❌ Категория не найдена.")
        await workout_manage(callback, bot, state)
        await callback.answer()
        return
    cat_name = row[0]
    await state.update_data(current_cat_id=cat_id)
    msg = await callback.message.answer(f"Категория: {cat_name}", reply_markup=workout_category_actions_keyboard(cat_id))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data.startswith("w_cat_rename_"))
async def workout_rename_category(callback: CallbackQuery, bot: Bot, state: FSMContext):
    cat_id = int(callback.data.split("_")[3])
    await state.update_data(renaming_cat_id=cat_id)
    await callback.message.delete()
    await state.set_state(WorkoutState.renaming_category)
    msg = await callback.message.answer("Введи новое название для категории:",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.message(WorkoutState.renaming_category)
async def workout_rename_category_finish(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    new_name = message.text.strip()
    if len(new_name) < 2:
        await message.answer("❌ Слишком короткое название. Попробуй ещё раз:")
        return
    data = await state.get_data()
    cat_id = data.get('renaming_cat_id')
    await state.clear()
    try:
        await message.delete()
    except:
        pass
    if not cat_id:
        await workout_manage_after_action(user_id, message.chat.id, bot)
        return
    try:
        db.execute('UPDATE exercise_categories SET name = ? WHERE id = ? AND user_id = ?', (new_name, cat_id, user_id))
        db.commit()
    except sqlite3.IntegrityError:
        await message.answer("❌ Категория с таким именем уже существует.")
    await workout_manage_after_action(user_id, message.chat.id, bot)



@router.callback_query(F.data.regexp(r'^w_cat_delete_\d+$'))
async def workout_delete_category_confirm(callback: CallbackQuery, bot: Bot, state: FSMContext):
    cat_id = int(callback.data.split("_")[3])
    await state.update_data(deleting_cat_id=cat_id)
    await callback.message.delete()
    await state.set_state(WorkoutState.deleting_category_confirm)
    msg = await callback.message.answer(
        "⚠️ Ты уверен, что хочешь удалить эту категорию? Все упражнения внутри тоже будут удалены.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb([
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data="w_cat_delete_yes"),
             InlineKeyboardButton(text="❌ Нет", callback_data="workout_manage")]
        ]))
    )
    user_temp_messages.setdefault(callback.from_user.id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data == "w_cat_delete_yes", WorkoutState.deleting_category_confirm)
async def workout_delete_category_finish(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    cat_id = data.get('deleting_cat_id')
    if not cat_id:
        await state.clear()
        await workout_manage_after_action(user_id, callback.message.chat.id, bot)
        await callback.answer()
        return
    db.execute('DELETE FROM exercise_categories WHERE id = ? AND user_id = ?', (cat_id, user_id))
    db.commit()
    await state.clear()
    await callback.message.delete()
    success_msg = await callback.message.answer("✅ Категория удалена.")
    await asyncio.sleep(2)
    await delete_message_safe(bot, callback.message.chat.id, success_msg.message_id)
    await workout_manage_after_action(user_id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(F.data.regexp(r'^w_manage_exercises_\d+$'))
async def workout_manage_exercises(callback: CallbackQuery, bot: Bot, state: FSMContext):
    cat_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT name FROM exercise_categories WHERE id = ?', (cat_id,))
    cat_row = cursor.fetchone()
    if not cat_row:
        await callback.message.answer("❌ Категория не найдена.")
        await workout_manage(callback, bot, state)
        await callback.answer()
        return
    cat_name = cat_row[0]
    ex_cursor = db.execute('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', (user_id, cat_id))
    exercises = ex_cursor.fetchall()
    await state.update_data(current_cat_id=cat_id)
    msg = await callback.message.answer(
        f"Упражнения в категории '{cat_name}':",
        reply_markup=workout_exercises_keyboard(exercises, cat_id, action="manage")
    )
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data == "w_back_to_cats_from_ex")
async def workout_back_to_cats_from_ex(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT id, name FROM exercise_categories WHERE user_id = ? ORDER BY name', (user_id,))
    categories = cursor.fetchall()
    await state.set_state(WorkoutState.choosing_category)
    msg = await callback.message.answer(
        "Выбери категорию упражнения:",
        reply_markup=workout_categories_keyboard(categories, action="add")
    )
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data == "w_back_to_ex_from_actions")
async def workout_back_to_ex_from_actions(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await workout_manage(callback, bot, state)



@router.callback_query(F.data.startswith("w_manage_ex_"))
async def workout_manage_view_exercise(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT name, category_id FROM exercises WHERE id = ?', (ex_id,))
    row = cursor.fetchone()
    if not row:
        await callback.message.answer("❌ Упражнение не найдено.")
        await workout_manage(callback, bot, state)
        await callback.answer()
        return
    ex_name, cat_id = row
    await state.update_data(current_ex_id=ex_id, current_cat_id=cat_id)
    msg = await callback.message.answer(f"Упражнение: {ex_name}", reply_markup=workout_exercise_actions_keyboard(ex_id))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data.startswith("w_ex_set_goal_"))
async def workout_set_goal_from_manage(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_id = int(callback.data.split("_")[4])
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT category_id FROM exercises WHERE id = ? AND user_id = ?', (ex_id, user_id))
    row = cursor.fetchone()
    if not row:
        await callback.answer("❌ Упражнение не найдено", show_alert=True)
        return
    cat_id = row[0]
    await state.update_data(creating_ex_id=ex_id, category_id=cat_id)
    await state.set_state(WorkoutState.setting_goal_type)
    msg = await callback.message.answer(
        "Выбери тип цели:",
        reply_markup=workout_exercise_goal_keyboard()
    )
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data.regexp(r'^w_ex_new_\d+$'))
async def workout_new_exercise(callback: CallbackQuery, bot: Bot, state: FSMContext):
    cat_id = int(callback.data.split("_")[3])
    await state.update_data(category_id=cat_id)
    await callback.message.delete()
    await state.set_state(WorkoutState.creating_exercise)
    msg = await callback.message.answer("Введи название нового упражнения (например, 'Жим лёжа', 'Бег'):",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.message(WorkoutState.creating_exercise)
async def workout_create_exercise(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    ex_name = message.text.strip()
    if len(ex_name) < 2:
        await message.answer("❌ Слишком короткое название. Попробуй ещё раз:")
        return
    data = await state.get_data()
    cat_id = data.get('category_id')
    if not cat_id:
        await state.clear()
        await workout_manage_after_action(user_id, message.chat.id, bot)
        return
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))
    try:
        cursor = db.execute('INSERT INTO exercises (user_id, category_id, name) VALUES (?, ?, ?)', (user_id, cat_id, ex_name))
        db.commit()
        new_ex_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        await message.answer("❌ Такое упражнение уже есть в этой категории.")
        await workout_manage_exercises_cat(user_id, message.chat.id, cat_id, bot)
        return
    await state.update_data(creating_ex_id=new_ex_id)
    await prompt_set_goal(message, bot, state, user_id, cat_id)



async def prompt_set_goal(message: Message, bot: Bot, state: FSMContext, user_id: int, cat_id: int):
    await state.set_state(WorkoutState.setting_goal_type)
    msg = await message.answer(
        "Хочешь установить цель для этого упражнения?\nВыбери тип:",
        reply_markup=workout_exercise_goal_keyboard()
    )
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id



@router.callback_query(WorkoutState.setting_goal_type, F.data == "goal_strength")
async def set_goal_strength(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await state.set_state(WorkoutState.setting_strength_goal)
    msg = await callback.message.answer(
        "Введи цель для силового упражнения в формате: подходы x повторения (например, 3x10)\n"
        "Если хочешь указать целевой вес и шаг увеличения, добавь ещё два числа через пробел: 3x10 50 2.5",
        reply_markup=back_reply_keyboard()
    )
    user_temp_messages.setdefault(callback.from_user.id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.message(WorkoutState.setting_strength_goal)
async def set_strength_goal_finish(message: Message, bot: Bot, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))

    parts = text.split()
    if not parts:
        await message.answer("❌ Введи цель (например, 3x10 или 10 8 6).")
        return

    goal_part = parts[0]
    numbers = []
    for part in parts[1:]:
        try:
            num = float(part.replace(',', '.'))
            numbers.append(num)
        except ValueError:
            continue

    target_weight = numbers[0] if len(numbers) > 0 else None
    weight_increment = numbers[1] if len(numbers) > 1 else None

    try:
        target_sets, target_reps_list = parse_reps_input(goal_part)
        target_reps = ','.join(str(r) for r in target_reps_list)
    except ValueError:
        msg = await message.answer("❌ Неверный формат цели. Используй примеры:\n- 3x10\n- 10 8 6\n- 3x10 50 2.5")
        user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
        return

    data = await state.get_data()
    ex_id = data.get('creating_ex_id')
    if not ex_id:
        await state.clear()
        await workout_manage_after_action(user_id, message.chat.id, bot)
        return

    db.execute('''
        UPDATE exercises
        SET target_sets = ?, target_reps = ?, target_weight = ?, weight_increment = ?
        WHERE id = ? AND user_id = ?
    ''', (target_sets, target_reps, target_weight, weight_increment, ex_id, user_id))
    db.commit()

    await state.clear()
    success_msg = await message.answer("✅ Цель установлена!")
    await asyncio.sleep(2)
    await delete_message_safe(bot, message.chat.id, success_msg.message_id)
    await workout_manage_exercises_cat(user_id, message.chat.id, data.get('category_id'), bot)



@router.callback_query(WorkoutState.setting_goal_type, F.data == "goal_cardio")
async def set_goal_cardio(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await state.set_state(WorkoutState.setting_cardio_goal)
    msg = await callback.message.answer(
        "Введи цель для кардио в формате: дистанция км / время мин (например, 5 30)",
        reply_markup=back_reply_keyboard()
    )
    user_temp_messages.setdefault(callback.from_user.id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.message(WorkoutState.setting_cardio_goal)
async def set_cardio_goal_finish(message: Message, bot: Bot, state: FSMContext):
    text = message.text.strip()
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('workout_temp'))

    parts = text.split()
    if len(parts) != 2:
        msg = await message.answer("❌ Нужно два числа: дистанция (км) и время (мин).")
        user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
        return

    try:
        target_distance = float(parts[0].replace(',', '.'))
        target_duration = int(parts[1])
    except ValueError:
        msg = await message.answer("❌ Неверный формат чисел.")
        user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
        return

    data = await state.get_data()
    ex_id = data.get('creating_ex_id')
    cat_id = data.get('category_id')
    
    if ex_id:
        db.execute('''
            UPDATE exercises
            SET target_distance = ?, target_duration = ?
            WHERE id = ? AND user_id = ?
        ''', (target_distance, target_duration, ex_id, user_id))
        db.commit()
        success_msg = "✅ Новая цель для кардио установлена!"
    else:
        success_msg = "✅ Цель установлена (но упражнение не найдено)!"

    await state.clear()
    success_msg_obj = await message.answer(success_msg)
    await asyncio.sleep(2)
    await delete_message_safe(bot, message.chat.id, success_msg_obj.message_id)
    if cat_id:
        await workout_manage_exercises_cat(user_id, message.chat.id, cat_id, bot)
    else:
        await workout_manage_after_action(user_id, message.chat.id, bot)



async def workout_manage_exercises_cat(user_id: int, chat_id: int, cat_id: int, bot: Bot):
    temps = user_temp_messages.get(user_id, {})
    old = temps.pop('workout_temp', None)
    if old:
        await delete_message_safe(bot, chat_id, old)
    cursor = db.execute('SELECT name FROM exercise_categories WHERE id = ?', (cat_id,))
    cat_row = cursor.fetchone()
    cat_name = cat_row[0] if cat_row else "Категория"
    ex_cursor2 = db.execute('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', (user_id, cat_id))
    exercises = ex_cursor2.fetchall()
    msg = await bot.send_message(
        chat_id,
        f"Упражнения в категории '{cat_name}':",
        reply_markup=workout_exercises_keyboard(exercises, cat_id, action="manage")
    )
    temps['workout_temp'] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(F.data.regexp(r'^w_ex_rename_\d+$'))
async def workout_rename_exercise(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_id = int(callback.data.split("_")[3])
    await state.update_data(renaming_ex_id=ex_id)
    await callback.message.delete()
    await state.set_state(WorkoutState.renaming_exercise)
    msg = await callback.message.answer("Введи новое название для категории:",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.message(WorkoutState.renaming_exercise)
async def workout_rename_exercise_finish(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    new_name = message.text.strip()
    if len(new_name) < 2:
        await message.answer("❌ Слишком короткое название. Попробуй ещё раз:")
        return
    data = await state.get_data()
    ex_id = data.get('renaming_ex_id')
    await state.clear()
    try:
        await message.delete()
    except:
        pass
    cursor = db.execute('SELECT category_id FROM exercises WHERE id = ?', (ex_id,)) if ex_id else None
    row = cursor.fetchone() if cursor else None
    cat_id = row[0] if row else None
    if not ex_id:
        await workout_manage_after_action(user_id, message.chat.id, bot)
        return
    try:
        db.execute('UPDATE exercises SET name = ? WHERE id = ? AND user_id = ?', (new_name, ex_id, user_id))
        db.commit()
    except sqlite3.IntegrityError:
        await message.answer("❌ Упражнение с таким именем уже существует в этой категории.")
    if cat_id:
        await workout_manage_exercises_cat(user_id, message.chat.id, cat_id, bot)
    else:
        await workout_manage_after_action(user_id, message.chat.id, bot)



@router.callback_query(F.data.regexp(r'^w_ex_delete_\d+$'))
async def workout_delete_exercise_confirm(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_id = int(callback.data.split("_")[3])
    await state.update_data(deleting_ex_id=ex_id)
    await callback.message.delete()
    await state.set_state(WorkoutState.deleting_exercise_confirm)
    msg = await callback.message.answer(
        "⚠️ Ты уверен, что хочешь удалить это упражнение?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb([
            [InlineKeyboardButton(text="Пропустить →", callback_data="wp_notes_skip")]
        ]))
    )
    user_temp_messages.setdefault(callback.from_user.id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(F.data == "w_ex_delete_yes", WorkoutState.deleting_exercise_confirm)
async def workout_delete_exercise_finish(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    ex_id = data.get('deleting_ex_id')
    if not ex_id:
        await state.clear()
        await workout_manage_after_action(user_id, callback.message.chat.id, bot)
        await callback.answer()
        return
    cursor = db.execute('SELECT category_id FROM exercises WHERE id = ?', (ex_id,))
    row = cursor.fetchone()
    cat_id = row[0] if row else None
    db.execute('DELETE FROM exercises WHERE id = ? AND user_id = ?', (ex_id, user_id))
    db.commit()
    await state.clear()
    await callback.message.delete()
    success_msg = await callback.message.answer("✅ Упражнение удалено.")
    await asyncio.sleep(2)
    await delete_message_safe(bot, callback.message.chat.id, success_msg.message_id)
    if cat_id:
        await workout_manage_exercises_cat(user_id, callback.message.chat.id, cat_id, bot)
    else:
        await workout_manage_after_action(user_id, callback.message.chat.id, bot)
    await callback.answer()



async def show_workout_history_page(user_id: int, chat_id: int, bot: Bot, page: int = 0, edit_msg_id: int = None):
    cursor = db.execute("""
        SELECT id, date, weekday, session_key, plan_json, status, skip_reason, feedback
        FROM ai_workout_sessions WHERE user_id = ? AND status != 'pending'
        ORDER BY date DESC
    """, (user_id,))
    rows = cursor.fetchall()
    if not rows:
        text = "Тренировок пока нет."
        if edit_msg_id:
            try:
                await bot.edit_message_text(text, chat_id, edit_msg_id)
                nav_push(user_id, "workout_history")
                return
            except:
                pass
        msg = await bot.send_message(chat_id, text)
        user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
        nav_push(user_id, "workout_history")
        return
    total = len(rows)
    page = max(0, min(page, total - 1))
    row = rows[page]
    session = dict(row)
    session["plan"] = json.loads(session["plan_json"])
    session["logs"] = get_session_exercise_logs(session["id"])
    text = _format_session_detail(session)
    nav = []
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="← Раньше", callback_data=f"wh_page_{page+1}"))
    if page > 0:
        nav.append(InlineKeyboardButton(text="Позже →", callback_data=f"wh_page_{page-1}"))
    kb_rows = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text=f"{total - page}/{total}", callback_data="wh_noop")])
    kb = InlineKeyboardMarkup(inline_keyboard=with_back_kb(kb_rows))
    if edit_msg_id:
        try:
            await bot.edit_message_text(text, chat_id, edit_msg_id, reply_markup=kb)
            return
        except:
            pass
    msg = await bot.send_message(chat_id, text, reply_markup=kb)
    user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
    nav_push(user_id, "workout_history")



@router.message(F.text == "✏️ Изменить упражнение")
async def workout_edit_exercise_start(message: Message, bot: Bot, state: FSMContext):
    try:
        await message.delete()
    except:
        pass
    user_id = message.from_user.id
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        return
    plan = plan_data.get("plan", {})
    # Collect all training days
    day_names = {"monday":"Пн","tuesday":"Вт","wednesday":"Ср","thursday":"Чт",
                 "friday":"Пт","saturday":"Сб","sunday":"Вс"}
    day_order = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    cycle = plan_data.get("cycle_weeks", 1)
    buttons = []
    seen_days = set()
    for w in range(1, cycle + 1):
        week = plan.get(f"week_{w}", {})
        for day_key in day_order:
            if day_key in week and day_key not in seen_days:
                seen_days.add(day_key)
                buttons.append([InlineKeyboardButton(
                    text=day_names[day_key],
                    callback_data=f"wex_day_{day_key}"
                )])
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, temps.pop('workout_menu', None))
    msg = await message.answer("Выбери день тренировки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons)))
    user_temp_messages.setdefault(user_id, {})['workout_menu'] = msg.message_id
    nav_push(user_id, "wex_days")
    await state.set_state(AIPlanState.editing_plan)
    await state.update_data(wp_edit_mode="exercise")



@router.callback_query(AIPlanState.editing_plan, F.data.startswith("wex_day_"))
async def workout_edit_choose_day(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    day_key = callback.data.split("_")[2]
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        await callback.answer("Нет плана", show_alert=True)
        return
    plan = plan_data.get("plan", {})
    cycle = plan_data.get("cycle_weeks", 1)
    # Find exercises for this day across all weeks (use first week that has it)
    exercises = []
    for w in range(1, cycle + 1):
        week = plan.get(f"week_{w}", {})
        exs = week.get(day_key, [])
        if exs:
            exercises = exs
            break
    if not exercises:
        await callback.answer("Нет упражнений", show_alert=True)
        return
    await state.update_data(wp_edit_day=day_key)
    buttons = []
    for i, ex in enumerate(exercises):
        name = ex.get("exercise", ex.get("name", f"Упражнение {i+1}"))
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"wex_ex_{i}")])
    await callback.message.edit_text("Выбери упражнение для замены:", reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons)))
    nav_push(callback.from_user.id, "wex_ex")
    await callback.answer()



@router.callback_query(AIPlanState.editing_plan, F.data == "wex_back_to_days")
async def workout_edit_back_to_days(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        await callback.answer()
        return
    plan = plan_data.get("plan", {})
    day_names = {"monday":"Пн","tuesday":"Вт","wednesday":"Ср","thursday":"Чт",
                 "friday":"Пт","saturday":"Сб","sunday":"Вс"}
    day_order = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    cycle = plan_data.get("cycle_weeks", 1)
    buttons = []
    seen_days = set()
    for w in range(1, cycle + 1):
        week = plan.get(f"week_{w}", {})
        for day_key in day_order:
            if day_key in week and day_key not in seen_days:
                seen_days.add(day_key)
                buttons.append([InlineKeyboardButton(text=day_names[day_key], callback_data=f"wex_day_{day_key}")])
    await callback.message.edit_text("Выбери день тренировки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons)))
    nav_push(callback.from_user.id, "wex_days")
    await callback.answer()



@router.callback_query(AIPlanState.editing_plan, F.data.startswith("wex_ex_"))
async def workout_edit_choose_exercise(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_idx = int(callback.data.split("_")[2])
    data = await state.get_data()
    day_key = data.get("wp_edit_day", "monday")
    plan_data = get_ai_plan(callback.from_user.id)
    if not plan_data:
        await callback.answer()
        return
    plan = plan_data.get("plan", {})
    cycle = plan_data.get("cycle_weeks", 1)
    exercises = []
    for w in range(1, cycle + 1):
        week = plan.get(f"week_{w}", {})
        exs = week.get(day_key, [])
        if exs:
            exercises = exs
            break
    if ex_idx >= len(exercises):
        await callback.answer("Упражнение не найдено", show_alert=True)
        return
    ex = exercises[ex_idx]
    ex_name = ex.get("exercise", ex.get("name", "?"))
    await state.update_data(wp_edit_ex_idx=ex_idx, wp_edit_ex_name=ex_name,
                            wp_edit_mode="exercise_replace")
    await callback.message.edit_text(
        f"Чем заменить «{ex_name}»?\n\nНапиши название нового упражнения:"
    )
    nav_push(callback.from_user.id, "wex_replace")
    await callback.answer()



@router.callback_query(F.data == "workout_history")
async def workout_history(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    user_history_page[user_id] = 0
    await show_history_page(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.callback_query(F.data.startswith("wh_page_"))
async def workout_history_page(callback: CallbackQuery, bot: Bot, state: FSMContext):
    page = int(callback.data.split("_")[2])
    await show_workout_history_page(callback.from_user.id, callback.message.chat.id, bot,
                                     page, callback.message.message_id)
    await callback.answer()



@router.callback_query(F.data == "wh_noop")
async def wh_noop(callback: CallbackQuery):
    await callback.answer()



@router.callback_query(F.data == "workout_history_back")
async def workout_history_back(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    try:
        await callback.message.delete()
    except:
        pass
    await show_workout_main_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



async def show_history_page(user_id: int, chat_id: int, bot: Bot, state: FSMContext, edit_message_id: int = None):
    page = user_history_page.get(user_id, 0)
    limit_days = 3
    offset_days = page * limit_days

    cursor = db.execute('''
        SELECT DISTINCT date
        FROM workout_log
        WHERE user_id = ?
        ORDER BY date DESC
    ''', (user_id,))
    all_dates = [row[0] for row in cursor.fetchall()]
    total_days = len(all_dates)
    total_pages = (total_days + limit_days - 1) // limit_days if total_days > 0 else 1

    if page >= total_pages and total_pages > 0:
        user_history_page[user_id] = total_pages - 1
        page = total_pages - 1
        offset_days = page * limit_days

    if total_days == 0:
        text = "📊 История тренировок пока пуста."
    else:
        start_idx = offset_days
        end_idx = min(offset_days + limit_days, total_days)
        page_dates = all_dates[start_idx:end_idx]

        lines = []
        for date in page_dates:
            day_cursor = db.execute('''
                SELECT wl.exercise_name, wl.sets, wl.reps, wl.weight, wl.distance, wl.duration, ec.name
                FROM workout_log wl
                LEFT JOIN exercise_categories ec ON wl.category_id = ec.id
                WHERE wl.user_id = ? AND wl.date = ?
                ORDER BY wl.id
            ''', (user_id, date))
            day_exercises = day_cursor.fetchall()

            formatted_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d.%m.%Y')
            lines.append(f"\n📅 {formatted_date}")

            for ex_name, sets, reps, weight, dist, dur, cat_name in day_exercises:
                if sets is not None:
                    line = f"  💪 {cat_name or 'Без категории'}: {ex_name} – {sets}х{reps}"
                    if weight:
                        line += f" ({weight} кг)"
                else:
                    line = f"  🚴 {cat_name or 'Кардио'}: {ex_name} – "
                    parts = []
                    if dist:
                        parts.append(f"{dist} км")
                    if dur:
                        parts.append(f"{dur} мин")
                    line += " / ".join(parts)
                lines.append(line)
        text = "📊 История тренировок\n" + "\n".join(lines)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data="history_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Следующая ➡️", callback_data="history_next"))

    keyboard_buttons = []
    if nav_buttons:
        keyboard_buttons.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(inline_keyboard=with_back_kb(keyboard_buttons))

    if edit_message_id:
        await bot.edit_message_text(text, chat_id, edit_message_id, reply_markup=reply_markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        user_temp_messages.setdefault(user_id, {})['workout_history'] = msg.message_id
    nav_push(user_id, "history")



@router.callback_query(F.data == "history_prev")
async def history_prev(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    page = user_history_page.get(user_id, 0)
    if page > 0:
        user_history_page[user_id] = page - 1
    await show_history_page(user_id, callback.message.chat.id, bot, state, edit_message_id=callback.message.message_id)
    await callback.answer()



@router.callback_query(F.data == "history_next")
async def history_next(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    page = user_history_page.get(user_id, 0)
    user_history_page[user_id] = page + 1
    await show_history_page(user_id, callback.message.chat.id, bot, state, edit_message_id=callback.message.message_id)
    await callback.answer()



async def _do_workout_charts(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    cursor = db.execute('SELECT id, name FROM exercise_categories WHERE user_id = ? ORDER BY name', (user_id,))
    categories = cursor.fetchall()
    if not categories:
        await bot.send_message(chat_id, "❌ Нет категорий для графиков")
        await show_workout_main_menu(user_id, chat_id, bot)
        return
    await state.set_state(WorkoutState.choosing_category)
    await state.update_data(workout_charts_mode=True)
    msg = await bot.send_message(chat_id, "Выбери категорию для графика:", reply_markup=workout_categories_keyboard(categories, action="add"))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id



@router.callback_query(F.data == "workout_charts")
async def workout_charts_start(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await _do_workout_charts(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.callback_query(WorkoutState.choosing_category, F.data.startswith("w_add_cat_"))
async def workout_charts_choose_category(callback: CallbackQuery, bot: Bot, state: FSMContext):
    cat_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await callback.message.delete()
    cursor = db.execute('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', (user_id, cat_id))
    exercises = cursor.fetchall()
    if not exercises:
        await callback.message.answer("❌ В этой категории нет упражнений.")
        await show_workout_main_menu(user_id, callback.message.chat.id, bot)
        await callback.answer()
        return
    await state.update_data(chart_cat_id=cat_id)
    await state.set_state(WorkoutState.choosing_exercise)
    msg = await callback.message.answer("Выбери упражнение для графика:", reply_markup=workout_exercises_keyboard(exercises, cat_id, action="add"))
    user_temp_messages.setdefault(user_id, {})['workout_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(WorkoutState.choosing_exercise, F.data.startswith("w_add_ex_"))
async def workout_charts_generate(callback: CallbackQuery, bot: Bot, state: FSMContext):
    ex_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await callback.message.delete()
    await state.clear()
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.UPLOAD_PHOTO)
    cursor = db.execute('''
        SELECT date, sets, reps, weight, distance, duration
        FROM workout_log
        WHERE user_id = ? AND exercise_name = (
            SELECT name FROM exercises WHERE id = ?
        )
        ORDER BY date
    ''', (user_id, ex_id))
    rows = cursor.fetchall()
    type_cursor2 = db.execute('SELECT ex_type FROM exercise_categories WHERE id = (SELECT category_id FROM exercises WHERE id = ?)', (ex_id,))
    type_row = type_cursor2.fetchone()
    ex_type = type_row[0] if type_row else 'strength'

    if len(rows) < 2:
        await callback.message.answer("❌ Недостаточно данных для графика (нужно минимум 2 записи).")
        await show_workout_main_menu(user_id, callback.message.chat.id, bot)
        await callback.answer()
        return

    chart_path = await run_in_thread(build_workout_progress_chart, user_id, rows, ex_type)
    photo = FSInputFile(chart_path)
    await callback.bot.send_photo(
        user_id,
        photo,
        caption="📈 Прогресс упражнения"
    )
    os.remove(chart_path)
    await callback.answer()



@router.callback_query(F.data.startswith("w_show_goal_"))
async def workout_show_goal(callback: CallbackQuery, bot: Bot):
    ex_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    cursor = db.execute('''
        SELECT name, target_sets, target_reps, target_weight, target_distance, target_duration 
        FROM exercises WHERE id = ? AND user_id = ?
    ''', (ex_id, user_id))
    row = cursor.fetchone()
    if not row:
        await callback.answer("❌ Упражнение не найдено", show_alert=True)
        return
    name, sets, reps, weight, dist, dur = row
    if sets and reps:
        text = f"🎯 Цель упражнения *{name}*:\n{sets}×{reps}" + (f" с весом {weight} кг" if weight else "")
    else:
        text = f"🎯 Цель упражнения *{name}*:\nДистанция {dist} км за {dur} мин"
    await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()
