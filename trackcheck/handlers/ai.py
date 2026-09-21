import asyncio
import os
import re

from aiogram import Bot, F
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    get_user_name, get_ai_plan, get_session_exercise_logs, get_next_training_day,
    get_or_create_rank_data, save_rating, save_last_ai_answer, add_spark,
    update_streak, check_all_categories_completed, get_last_ai_answer,
)
from trackcheck.states.category import RatingState
from trackcheck.states.workout import AIPlanState, WorkoutSessionState
from trackcheck.states.food import DietState
from trackcheck.states.settings import AIAdvisorState
from trackcheck.services.ai_service import (
    gemini_generate, gemini_generate_rating, gemini_generate_plan,
    gemini_parse_manual_plan, _fallback_parse_plan, gemini_session_feedback,
    gemini_monthly_review, get_full_context_for_ai, analyze_low_rating,
    analyze_food_photo, analyze_body_photo,
)
from trackcheck.services.workout_service import _format_full_plan
from trackcheck.services.gamification_service import get_rank_name
from trackcheck.utils.concurrency import run_in_thread, run_db
from trackcheck.utils.dates import user_today_str
from trackcheck.utils.bot_helpers import delete_message_safe, delete_temp_messages
from trackcheck.keyboards.common import retry_ai_keyboard
from trackcheck.keyboards.ai import ai_reply_keyboard, photo_analysis_back_keyboard
from trackcheck.keyboards.categories import reflection_keyboard
from trackcheck.keyboards.food import diet_confirm_food_keyboard
from trackcheck.keyboards.workouts import (
    wp_plan_review_keyboard, wp_plan_review_keyboard_manual, wp_edit_keyboard,
    wp_settings_keyboard, ws_rest_day_keyboard,
)
from trackcheck.runtime import user_temp_messages, user_last_menu, nav_push
from trackcheck.handlers.dashboard import send_main_menu
from trackcheck.handlers.categories import show_reflection_menu
from trackcheck.handlers import router


@router.callback_query(F.data.startswith("retry_ai:"))
async def retry_ai_action(callback: CallbackQuery, bot: Bot, state: FSMContext):
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if action == "mood":
        await state.set_state(RatingState.waiting_for_mood_text)
        await _retry_mood_rating(callback, bot, state)
    elif action == "ai_advice":
        await _retry_ai_advice(callback, bot, state)
    elif action == "ai_question":
        await _retry_ai_question(callback, bot, state)
    elif action == "generate_plan":
        await _retry_generate_plan(callback, bot, state)
    elif action == "low_rating":
        await _retry_low_rating(callback, bot, state)
    elif action == "food_calories":
        await _retry_food_calories(callback, bot, state)
    elif action == "food_photo":
        await _retry_food_photo(callback, bot, state)
    elif action == "photo_analysis":
        await _retry_photo_analysis(callback, bot, state)
    elif action == "manual_plan":
        await _retry_manual_plan(callback, bot, state)
    elif action == "monthly_review":
        await _retry_monthly_review(callback, bot, state)
    elif action == "session_feedback":
        await _retry_session_feedback(callback, bot, state)
    await callback.answer()



async def _retry_mood_rating(callback, bot, state):
    data = await state.get_data()
    description = data.get("retry_mood_description", "")
    user_id = callback.from_user.id
    name = await run_db(get_user_name, user_id, callback.from_user.first_name)
    full_context = await run_db(get_full_context_for_ai, user_id)
    prompt = f"""Ты — заботливый персональный трекер-ассистент. Пользователя зовут {name}.
Он(а) описал(а) свой сегодняшний день и настроение так: "{description}"

Вот что ты ещё знаешь о нём(ней) за последнее время:
{full_context}

Оцени его(её) настроение сегодня по шкале от 1 до 10 (10 — отличное настроение, 1 — очень плохое).
Затем напиши короткий (2-4 предложения) тёплый отклик по-русски, обращаясь по имени:
- если настроение хорошее — искренне порадуйся вместе с ним(ней);
- если настроение так себе или плохое — мягко поддержи и дай 1-2 конкретных совета,
  как можно улучшить состояние или разобраться с тяжёлыми эмоциями, учитывая контекст выше.
Ответь СТРОГО в формате JSON без пояснений и без markdown:
{{"rating": <целое число 1-10>, "response": "<текст отклика>"}}"""
    result = await run_in_thread(gemini_generate_rating, prompt)
    if not result:
        await callback.message.edit_text(
            "❌ ИИ не ответил. Попробуй ещё раз.",
            reply_markup=retry_ai_keyboard("mood")
        )
        return
    today = user_today_str(user_id)
    rating = result['rating']
    await run_db(save_rating, user_id, 'настрой', rating, today)
    reply_text = f"🎯 Настрой: {rating}/10\n\n{result.get('response') or result.get('comment', '')}"
    await callback.message.edit_text(reply_text, reply_markup=reflection_keyboard())
    await state.clear()
    all_completed = await run_db(check_all_categories_completed, user_id)
    if all_completed:
        await run_db(add_spark, user_id, 'categories')
        await run_db(update_streak, user_id)
        await send_main_menu(bot, callback.from_user.id, callback.message.chat.id)
    else:
        await show_reflection_menu(user_id, callback.message.chat.id, bot, state, callback.from_user.first_name)



async def _retry_ai_advice(callback, bot, state):
    data = await state.get_data()
    user_id = callback.from_user.id
    name = await run_db(get_user_name, user_id, callback.from_user.first_name)
    full_context = await run_db(get_full_context_for_ai, user_id)
    prompt = data.get("retry_ai_prompt", "")
    try:
        answer = await run_in_thread(gemini_generate, prompt, 8192)
    except:
        answer = "❌ Ошибка ИИ."
    if answer.startswith("❌"):
        await callback.message.edit_text(
            f"❌ ИИ не ответил. Попробуй ещё раз.",
            reply_markup=retry_ai_keyboard("ai_advice")
        )
        return
    await callback.message.edit_text(
        f"💡 <b>Совет:</b>\n\n{answer}",
        parse_mode="HTML", reply_markup=ai_reply_keyboard()
    )
    await run_db(save_last_ai_answer, user_id, answer)



async def _retry_ai_question(callback, bot, state):
    data = await state.get_data()
    user_id = callback.from_user.id
    name = await run_db(get_user_name, user_id, callback.from_user.first_name)
    full_context = await run_db(get_full_context_for_ai, user_id)
    question = data.get("retry_ai_question", "")
    prompt = f"""Ты — персональный трекер-ассистент. Пользователь {name}.

Вот свежие данные пользователя:
{full_context}

Вопрос: {question}
Ответь кратко, конкретно, с эмодзи, обращайся по имени."""
    try:
        answer = await run_in_thread(gemini_generate, prompt, 8192)
    except:
        answer = "❌ Ошибка ИИ."
    if answer.startswith("❌"):
        await callback.message.edit_text(
            f"❌ ИИ не ответил. Попробуй ещё раз.",
            reply_markup=retry_ai_keyboard("ai_question")
        )
        return
    await callback.message.edit_text(
        f"🤖 <b>Check AI:</b>\n\n{answer}",
        parse_mode="HTML", reply_markup=ai_reply_keyboard()
    )
    await run_db(save_last_ai_answer, user_id, answer)



async def _retry_generate_plan(callback, bot, state):
    data = await state.get_data()
    user_id = callback.from_user.id
    goal = data.get("wp_goal", "Общая форма")
    level = data.get("wp_level", "Средний")
    days = data.get("wp_days", 3)
    notes = data.get("wp_notes", "")
    await state.set_state(AIPlanState.reviewing_plan)
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
        await callback.message.edit_text(
            "Не удалось сгенерировать план. Попробуй ещё раз.",
            reply_markup=retry_ai_keyboard("generate_plan")
        )
        return
    await state.update_data(wp_plan=plan)
    text = _format_full_plan(plan, goal, level, days)
    await callback.message.edit_text(text, reply_markup=wp_plan_review_keyboard())



async def _retry_low_rating(callback, bot, state):
    data = await state.get_data()
    category = data.get("retry_low_rating_category", "")
    rating = data.get("retry_low_rating_value", 0)
    user_id = callback.from_user.id
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.TYPING)
    analysis = await run_in_thread(analyze_low_rating, user_id, category, rating)
    if analysis.startswith("❌"):
        # ИИ снова не ответил — оставляем ту же кнопку повтора
        await callback.message.edit_text(
            "❌ ИИ не ответил. Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("low_rating")
        )
        return
    msg = await callback.message.answer(f"🤖 {analysis}", reply_markup=ai_reply_keyboard())
    save_last_ai_answer(user_id, analysis)



async def _retry_food_calories(callback, bot, state):
    data = await state.get_data()
    description = data.get("retry_food_description", "")
    user_id = callback.from_user.id
    prompt = f"""Ты — точный счётчик калорий. Пользователь описывает что он съел (на русском или английском языке).

Твоя задача: посчитать ОБЩЕЕ количество ккал во всём описанном количестве еды.

ПРАВИЛА:
- Если указано количество (2 бургера, 3 яйца, 200г) — умножай соответственно
- Если количество не указано — считай стандартную порцию (тарелка супа ~300мл, второе блюдо ~300-400г, бутерброд ~150г)
- Учитывай ВСЕ компоненты: хлеб, масло, соусы, напитки, гарнир
- Не занижай: реальная еда жирнее и калорийнее чем кажется
- Минимум для полноценного приёма пищи (обед/ужин): 350 ккал
- Перекус может быть 100-300 ккал

Ориентиры (на порцию):
гречка с курицей = 450, паста карбонара = 680, бургер = 550, пицца (2 куска) = 600,
борщ = 300, салат цезарь с курицей = 520, омлет 2 яйца = 200, овсянка на молоке = 280,
рис с мясом = 500, шаурма = 650, хинкали 5шт = 400, суши-сет 8шт = 480,
протеиновый коктейль = 150, кофе с молоком = 60, яблоко = 80, банан = 100

Еда: {description}

Ответь СТРОГО одним целым числом — суммарные килокалории. Никаких слов, никаких единиц:"""
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.TYPING)
    response = await run_in_thread(gemini_generate, prompt, 100, True)
    try:
        numbers = re.findall(r"\b(\d{2,5})\b", response)
        numbers = [float(n) for n in numbers if 50 <= float(n) <= 9999]
        calories = numbers[-1] if numbers else None
    except:
        calories = None
    if calories is None or calories <= 0:
        # ИИ снова не смог — оставляем кнопку повтора, не заставляя вводить руками
        await callback.message.edit_text(
            f"❌ Не удалось определить калории для «{description}». "
            "Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("food_calories")
        )
        return
    await state.update_data(food_description=description, food_calories=calories)
    await state.set_state(DietState.food_confirm)
    await callback.message.edit_text(
        f"🍽 Ты съел: {description}\n🔢 Калории: {int(calories)} ккал\n\nВсё верно?",
        reply_markup=diet_confirm_food_keyboard()
    )



async def _retry_photo_analysis(callback, bot, state):
    data = await state.get_data()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    image_bytes = data.get("retry_photo_bytes")
    prompt = data.get("retry_photo_prompt", """Кратко проанализируй телосложение на фото. Формат ответа:
• Сильные стороны (1-2 предложения)
• Слабые стороны (1-2 предложения)
• Рекомендации (2-3 конкретных совета)
Без воды, по делу, макс 150 слов.""")
    try:
        analysis = await run_in_thread(analyze_body_photo, image_bytes, prompt) or "❌ Нет ответа"
    except Exception as e:
        analysis = f"❌ Ошибка: {str(e)[:100]}"
    if analysis.startswith("❌"):
        await callback.message.edit_text(
            analysis + "\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("photo_analysis")
        )
        return
    await callback.message.edit_text(analysis, reply_markup=photo_analysis_back_keyboard())
    temps = user_temp_messages.get(user_id, {})
    temps['photo_analysis_result'] = callback.message.message_id
    user_temp_messages[user_id] = temps
    await state.clear()



async def _retry_food_photo(callback, bot, state):
    """Повторный анализ того же фото блюда без повторной загрузки."""
    data = await state.get_data()
    user_id = callback.from_user.id
    image_bytes = data.get("retry_food_photo_bytes")
    prompt = data.get("retry_food_photo_prompt")
    if not image_bytes or not prompt:
        await callback.message.edit_text(
            "❌ Фото больше не доступно. Отправь его заново."
        )
        return
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.TYPING)
    text = await run_in_thread(analyze_food_photo, image_bytes, prompt)
    if text is None:
        await callback.message.edit_text(
            "❌ Ошибка анализа фото.\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("food_photo")
        )
        return
    description = "Блюдо на фото"
    calories = None
    nums = re.findall(r"\b(\d{2,5})\b", text)
    valid_nums = [float(n) for n in nums if 50 <= float(n) <= 9999]
    if valid_nums:
        calories = valid_nums[-1]
    match = re.search(r"^([^0-9]+?)(?:\s*\d|$)", text)
    if match:
        desc = match.group(1).strip(" .,;:-")
        if 2 <= len(desc) <= 50:
            description = desc
    if calories is None or calories <= 0 or calories > 5000:
        await callback.message.edit_text(
            f"🍽 Определено: {description}\n"
            "❌ Не удалось оценить калории.\n\n"
            "🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("food_photo")
        )
        return
    await state.update_data(food_description=description, food_calories=calories)
    await state.set_state(DietState.food_confirm)
    await callback.message.edit_text(
        f"🍽 Ты съел: {description}\n🔢 Калории: ~{int(calories)} ккал\n\nВсё верно?",
        reply_markup=diet_confirm_food_keyboard()
    )



async def _retry_manual_plan(callback, bot, state):
    """Повторный разбор того же текста плана без повторного ввода."""
    data = await state.get_data()
    user_id = callback.from_user.id
    raw_text = data.get("retry_manual_plan_text", "")
    if not raw_text:
        await callback.message.edit_text(
            "❌ Текст плана не сохранился. Введи его заново.",
            reply_markup=wp_edit_keyboard()
        )
        return
    await state.set_state(AIPlanState.reviewing_plan)
    temps = user_temp_messages.get(user_id, {})
    # Кнопка повтора живёт на сообщении об ошибке — его и редактируем
    msg_id = callback.message.message_id
    temps['workout_menu'] = msg_id
    user_temp_messages[user_id] = temps
    stop_anim = asyncio.Event()
    phrases_m = ["Читаю план...", "Разбираю структуру...", "Определяю дни...",
                 "Считаю подходы...", "Почти готово..."]

    async def animate_m():
        i = 0
        while not stop_anim.is_set():
            try:
                await bot.edit_message_text(phrases_m[i % len(phrases_m)],
                                            callback.message.chat.id, msg_id)
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
    if not plan:
        plan = await run_in_thread(_fallback_parse_plan, raw_text)
    if not plan:
        # Возвращаемся в режим ввода — можно и нажать повторно, и переописать план
        await state.set_state(AIPlanState.entering_manual_plan)
        await callback.message.edit_text(
            "❌ Не смог разобрать план.\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("manual_plan")
        )
        return
    await state.update_data(wp_plan=plan, wp_mode="manual",
                            wp_goal="", wp_level="", wp_days=0)
    text = _format_full_plan(plan, "", "", 0)
    try:
        await bot.edit_message_text(text, callback.message.chat.id, msg_id,
                                    reply_markup=wp_plan_review_keyboard_manual())
    except:
        new_msg = await callback.message.answer(text,
                                                reply_markup=wp_plan_review_keyboard_manual())
        temps['workout_menu'] = new_msg.message_id
        user_temp_messages[user_id] = temps



async def _retry_monthly_review(callback, bot, state):
    """Повторный запуск месячного пересмотра упражнений."""
    user_id = callback.from_user.id
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        await callback.answer("Нет плана", show_alert=True)
        return
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.TYPING)
    await callback.message.edit_text("Анализирую прогресс...")
    cursor = db.execute("""
        SELECT date, plan_json, status FROM ai_workout_sessions
        WHERE user_id = ? ORDER BY date DESC LIMIT 20
    """, (user_id,))
    recent = [{"date": row[0], "status": row[2]} for row in cursor.fetchall()]
    changes = await run_in_thread(gemini_monthly_review, plan_data["plan"], recent)
    if not changes:
        await callback.message.edit_text(
            "❌ Не удалось проанализировать прогресс.\n\n"
            "🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("monthly_review")
        )
        return
    if changes.get("no_changes_needed") or not changes.get("changes"):
        await callback.message.edit_text(
            "Менять ничего не нужно — план хорошо сбалансирован.",
            reply_markup=wp_settings_keyboard()
        )
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



@router.callback_query(F.data == "menu_ai")
async def handle_ai(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await state.clear()
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[user_id] = None
    # Удаляем оставшиеся временные сообщения других разделов (фото/замеры/ИИ сохраняются)
    await delete_temp_messages(bot, user_id, callback.message.chat.id, keep_ai=True)
    temps = user_temp_messages.setdefault(user_id, {})
    msg = await callback.message.answer("🤖 CheckAI тут, чем помочь?", reply_markup=ai_reply_keyboard())
    temps['ai_advisor'] = msg.message_id
    nav_push(user_id, "ai")
    await state.set_state(AIAdvisorState.waiting_for_question)



@router.callback_query(F.data == "wp_edit_retry")
async def wp_edit_retry(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    plan_data = await run_db(get_ai_plan, callback.from_user.id)
    plan = data.get("wp_plan") or (plan_data or {}).get("plan")
    await state.set_state(AIPlanState.editing_plan)
    await state.update_data(wp_plan=plan)
    await callback.message.edit_text(
        "Что хочешь изменить в плане?\n\nНапиши например:\n«убери приседания, замени на жим ногами»",
        reply_markup=wp_edit_keyboard()
    )



@router.callback_query(F.data == "ai_advice")
async def handle_ai_advice(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    temps = user_temp_messages.get(user_id, {})
    # Удаляем вступительное сообщение бота (если ещё не удалено)
    await delete_message_safe(bot, callback.message.chat.id, temps.get('ai_advisor'))
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.TYPING)
    name = await run_db(get_user_name, user_id, callback.from_user.first_name)
    full_context = await run_db(get_full_context_for_ai, user_id)
    prompt = f"""Ты — персональный трекер-ассистент. Пользователь {name}.

Вот свежие данные пользователя:
{full_context}

Дай короткий персональный совет (3-5 предложений): что идёт хорошо, на что обратить внимание, и один конкретный шаг на сегодня/завтра.
Обращайся по имени, используй эмодзи, пиши по-русски."""
    await state.update_data(retry_ai_prompt=prompt, retry_action="ai_advice")
    # Animation while generating
    phrases_ai = ["Думаю.", "Думаю..", "Думаю...", "Анализирую.", "Анализирую..", "Анализирую..."]
    stop_ai = asyncio.Event()
    tmp = await callback.message.answer("Думаю...")
    ai_msg_id = tmp.message_id
    temps['ai_advisor'] = ai_msg_id
    user_temp_messages[user_id] = temps

    async def animate_ai():
        i = 0
        while not stop_ai.is_set():
            try:
                await bot.edit_message_text(phrases_ai[i % len(phrases_ai)],
                                             callback.message.chat.id, ai_msg_id)
            except:
                pass
            await asyncio.sleep(1)
            i += 1
    anim = asyncio.create_task(animate_ai())
    try:
        answer = await run_in_thread(gemini_generate, prompt, 8192)
    finally:
        stop_ai.set()
        anim.cancel()
        try:
            await anim
        except asyncio.CancelledError:
            pass
    if answer.startswith("❌"):
        try:
            await bot.edit_message_text("❌ ИИ не ответил.", callback.message.chat.id, ai_msg_id)
        except:
            pass
        await callback.message.answer(
            "❌ ИИ не ответил. Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("ai_advice")
        )
        await state.set_state(AIAdvisorState.waiting_for_question)
        return
    try:
        await bot.edit_message_text(
            f"💡 <b>Совет:</b>\n\n{answer}",
            callback.message.chat.id, ai_msg_id,
            parse_mode="HTML", reply_markup=ai_reply_keyboard()
        )
    except Exception:
        await delete_message_safe(bot, callback.message.chat.id, ai_msg_id)
        msg = await callback.message.answer(f"💡 <b>Совет:</b>\n\n{answer}",
                                            parse_mode="HTML", reply_markup=ai_reply_keyboard())
        ai_msg_id = msg.message_id
    temps['ai_response'] = ai_msg_id
    user_temp_messages[user_id] = temps
    await run_db(save_last_ai_answer, user_id, answer)
    await state.set_state(AIAdvisorState.waiting_for_question)



@router.message(AIAdvisorState.waiting_for_question)
async def process_ai_question(message: Message, bot: Bot, state: FSMContext):
    question = message.text.strip()
    if len(question) < 3:
        await message.answer("❌ Вопрос слишком короткий. Опиши подробнее!", reply_markup=ai_reply_keyboard())
        return
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    # Удаляем вступительное сообщение бота (НЕ вопрос пользователя!)
    await delete_message_safe(bot, message.chat.id, temps.get('ai_advisor'))
    await bot.send_chat_action(message.chat.id, action=ChatAction.TYPING)
    name = await run_db(get_user_name, user_id, message.from_user.first_name)
    full_context = await run_db(get_full_context_for_ai, user_id)
    await state.update_data(retry_ai_question=question, retry_action="ai_question")
    context = f"""Ты — персональный трекер-ассистент. Пользователь {name}.

Вот свежие данные пользователя:
{full_context}

Вопрос: {question}
Ответь кратко, конкретно, с эмодзи, обращайся по имени."""
    # Animation while generating
    phrases_ai = ["Думаю.", "Думаю..", "Думаю...", "Анализирую.", "Анализирую..", "Анализирую..."]
    stop_ai = asyncio.Event()
    # Отправляем сообщение для анимации
    tmp = await message.answer("Думаю...")
    ai_msg_id = tmp.message_id
    temps['ai_advisor'] = ai_msg_id
    user_temp_messages[user_id] = temps

    async def animate_ai():
        i = 0
        while not stop_ai.is_set():
            try:
                await bot.edit_message_text(phrases_ai[i % len(phrases_ai)],
                                             message.chat.id, ai_msg_id)
            except:
                pass
            await asyncio.sleep(1)
            i += 1
    anim = asyncio.create_task(animate_ai())
    try:
        answer = await run_in_thread(gemini_generate, context, 8192)
    finally:
        stop_ai.set()
        anim.cancel()
        try:
            await anim
        except asyncio.CancelledError:
            pass
    if answer.startswith("❌"):
        try:
            await bot.edit_message_text("❌ ИИ не ответил.", message.chat.id, ai_msg_id)
        except:
            pass
        await message.answer(
            "❌ ИИ не ответил. Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("ai_question")
        )
        await state.set_state(AIAdvisorState.waiting_for_question)
        return
    # Ответ ИИ с reply кнопкой - редактируем то же сообщение (не отправляем новое)
    try:
        await bot.edit_message_text(
            f"🤖 <b>Check AI:</b>\n\n{answer}",
            message.chat.id, ai_msg_id,
            parse_mode="HTML", reply_markup=ai_reply_keyboard()
        )
    except Exception as e:
        # Если редактирование не удалось - удаляем старое и отправляем новое
        await delete_message_safe(bot, message.chat.id, ai_msg_id)
        msg = await message.answer(f"🤖 <b>Check AI:</b>\n\n{answer}",
                                    parse_mode="HTML", reply_markup=ai_reply_keyboard())
        ai_msg_id = msg.message_id
    temps['ai_response'] = ai_msg_id
    user_temp_messages[user_id] = temps
    await run_db(save_last_ai_answer, user_id, answer)



@router.callback_query(F.data == "show_last_ai")
async def show_last_ai(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    last_answer = await run_db(get_last_ai_answer, user_id)
    if last_answer:
        await callback.message.answer(f"🤖 <b>Последний ответ ИИ:</b>\n\n{last_answer}", parse_mode="HTML", reply_markup=ai_reply_keyboard())
    else:
        await callback.answer("Нет сохранённого ответа", show_alert=True)



async def _retry_session_feedback(callback, bot, state):
    """Повторно генерирует ИИ-фидбек по завершённой тренировке."""
    data = await state.get_data()
    session_id = data.get("retry_session_id")
    exercises = data.get("retry_session_exercises") or []
    user_id = callback.from_user.id
    if not session_id:
        await callback.answer("Данные тренировки не найдены", show_alert=True)
        return
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.TYPING)
    logs = await run_db(get_session_exercise_logs, session_id)
    feedback = await run_in_thread(gemini_session_feedback, logs, exercises)
    if feedback.startswith("❌"):
        await callback.message.edit_text(
            "❌ ИИ снова не смог подготовить фидбек.\n\n"
            "🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("session_feedback")
        )
        return
    lines = ["Тренировка завершена\n"]
    for log in logs:
        if log["status"] == "skipped":
            lines.append(f"⏭ {log['exercise_name']} — пропущено")
        elif log.get("result") and log["result"].get("note"):
            lines.append(f"⚠️ {log['exercise_name']} — {log['result']['note']}")
    lines.append(f"\n{feedback}")
    plan_data = await run_db(get_ai_plan, user_id)
    next_date, next_day = get_next_training_day(plan_data, user_id) if plan_data else (None, None)
    if next_date:
        lines.append(f"\nСледующая тренировка: {next_day}, {next_date}")
    rank_data = await run_db(get_or_create_rank_data, user_id)
    if rank_data:
        lines.append(f"\n✨ Текущий ранг: {get_rank_name(rank_data['current_rank'])}!")
    await callback.message.edit_text("\n".join(lines),
                                      reply_markup=ws_rest_day_keyboard())
