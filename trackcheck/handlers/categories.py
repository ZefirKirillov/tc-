import asyncio
from typing import Optional

from aiogram import Bot, F
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from trackcheck.database.repositories import (
    get_user_name, update_streak, get_today_ratings, save_rating,
    check_all_categories_completed, manual_categories_completed, add_spark,
    save_last_ai_answer,
)
from trackcheck.states.category import RatingState
from trackcheck.services.ai_service import (
    gemini_generate_rating, get_full_context_for_ai, analyze_low_rating,
)
from trackcheck.services.gamification_service import get_rank_name
from trackcheck.utils.concurrency import run_db, run_in_thread
from trackcheck.utils.dates import user_today_str
from trackcheck.utils.bot_helpers import delete_message_safe, delete_temp_messages
from trackcheck.keyboards.common import back_reply_keyboard, retry_ai_keyboard
from trackcheck.keyboards.ai import ai_reply_keyboard
from trackcheck.keyboards.categories import (
    reflection_keyboard, rating_keyboard, low_rating_keyboard,
)
from trackcheck.runtime import user_last_menu, user_temp_messages, nav_push
from trackcheck.handlers.dashboard import send_main_menu
from trackcheck.handlers import router


async def show_reflection_menu(user_id: int, chat_id: int, bot: Bot, state: FSMContext, fallback_name: Optional[str] = None):
    await state.clear()
    name = get_user_name(user_id, fallback_name)
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, chat_id, old_menu)
        user_last_menu[user_id] = None
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.pop('reflection', None))
    await delete_message_safe(bot, chat_id, temps.pop('tasks_menu', None))
    # Проверяем, заполнены ли все категории — если да, запоминаем для последующего возврата в меню
    if check_all_categories_completed(user_id):
        temps['all_categories_filled'] = True
    else:
        temps.pop('all_categories_filled', None)
    user_temp_messages[user_id] = temps
    # Еда и активность теперь считаются автоматически (после лога еды/тренировки, либо в
    # конце дня) - если пользователь уже заполнил всё, что доступно ему вручную, незачем
    # бесконечно звать его обратно в "что оценим?" в ожидании авто-категорий.
    if manual_categories_completed(user_id):
        update_streak(user_id)
        await bot.send_message(
            chat_id,
            f"{name}, на сегодня с рефлексией всё! 🎉\n"
            "Еда и активность посчитаются сами, как только ты их залогируешь.",
        )
        await delete_temp_messages(bot, user_id, chat_id, keep_ai=True)
        await send_main_menu(bot, user_id, chat_id)
        return
    msg = await bot.send_message(chat_id, f"{name}, что оценим?", reply_markup=reflection_keyboard())
    nav_push(user_id, "reflection")
    user_temp_messages[user_id]['reflection'] = msg.message_id



@router.callback_query(F.data == "menu_reflection")
async def handle_reflection(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await show_reflection_menu(callback.from_user.id, callback.message.chat.id, bot, state, callback.from_user.first_name)
    await callback.answer()



@router.callback_query(F.data.startswith("refl:"))
async def handle_category(callback: CallbackQuery, bot: Bot, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    if category == "настрой":
        await callback.message.delete()
        temps = user_temp_messages.get(user_id, {})
        await delete_message_safe(bot, callback.message.chat.id, temps.get('reflection'))
        await state.set_state(RatingState.waiting_for_mood_text)
        msg = await callback.message.answer(
            "🎯 Опиши в паре предложений, как прошёл твой день и что ты сегодня чувствовал(а):",
            reply_markup=back_reply_keyboard()
        )
        temps['rating'] = msg.message_id
        user_temp_messages[user_id] = temps
        await callback.answer()
        return
    if category not in ("сон", "зависание"):
        await callback.answer()
        return
    await callback.message.delete()
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('reflection'))
    await state.update_data(category=category)
    await state.set_state(RatingState.waiting_for_rating)
    msg = await callback.message.answer(f"📝 Оцени {category.upper()} за сегодня:", reply_markup=rating_keyboard())
    temps['rating'] = msg.message_id
    user_temp_messages[user_id] = temps
    await callback.answer()



@router.message(RatingState.waiting_for_mood_text)
async def process_mood_text(message: Message, bot: Bot, state: FSMContext):
    description = (message.text or "").strip()
    if len(description) < 3:
        await message.answer("Напиши чуть подробнее, как прошёл день 🙂")
        return
    user_id = message.from_user.id
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('rating'))
    await bot.send_chat_action(message.chat.id, action=ChatAction.TYPING)
    thinking_msg = await message.answer("Думаю...")
    temps['rating'] = thinking_msg.message_id
    user_temp_messages[user_id] = temps

    name = get_user_name(user_id, message.from_user.first_name)
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

    await state.update_data(
        retry_mood_description=description,
        retry_action="mood"
    )
    result = await run_in_thread(gemini_generate_rating, prompt)
    if not result:
        await delete_message_safe(bot, message.chat.id, temps.get('rating'))
        await message.answer(
            "❌ ИИ не ответил.",
            reply_markup=retry_ai_keyboard("mood")
        )
        return

    today = user_today_str(user_id)
    rating = result['rating']
    save_rating(user_id, 'настрой', rating, today)
    reply_text = f"🎯 Настрой: {rating}/10\n\n{result.get('response') or result.get('comment', '')}"
    await state.clear()
    await delete_message_safe(bot, message.chat.id, temps.get('rating'))

    all_completed = check_all_categories_completed(user_id)
    if all_completed:
        success, sparks_today, rank_up, old_rank, new_rank = add_spark(user_id, 'categories')
        update_streak(user_id)
        await message.answer(reply_text)
        await delete_temp_messages(bot, user_id, message.chat.id, keep_ai=True)
        await send_main_menu(bot, user_id, message.chat.id)
    else:
        msg = await message.answer(reply_text, reply_markup=reflection_keyboard())
        temps = user_temp_messages.get(user_id, {})
        temps['rating'] = msg.message_id
        user_temp_messages[user_id] = temps
        await show_reflection_menu(user_id, message.chat.id, bot, state, message.from_user.first_name)



@router.callback_query(F.data.startswith("rate:"))
async def process_rating(callback: CallbackQuery, bot: Bot, state: FSMContext):
    temps = user_temp_messages.get(callback.from_user.id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('reflection'))
    data = await state.get_data()
    category = data.get("category")
    rating = int(callback.data.split(":")[1])
    today = user_today_str(callback.from_user.id)
    save_rating(callback.from_user.id, category, rating, today)
    await state.clear()
    temps = user_temp_messages.get(callback.from_user.id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('rating'))
    name = get_user_name(callback.from_user.id, callback.from_user.first_name)

    # Проверяем, заполнены ли все 5 категорий
    all_completed = check_all_categories_completed(callback.from_user.id)
    # Также проверяем флаг из temp messages (если пользователь зашел повторно при заполненных категориях)
    all_filled_flag = temps.get('all_categories_filled', False)

    if rating <= 3:
        # Если все категории заполнены — спрашиваем про ИИ анализ, но сохраняем флаг
        msg = await callback.message.answer(
            f"{name}, низкая оценка {category} ({rating}/10). Разобрать с ИИ почему так?",
            reply_markup=low_rating_keyboard(category)
        )
        temps['low_rating'] = msg.message_id
        if all_completed or all_filled_flag:
            temps['all_categories_filled'] = True
        user_temp_messages[callback.from_user.id] = temps
        await show_reflection_menu(callback.from_user.id, callback.message.chat.id, bot, state, callback.from_user.first_name)
    else:
        if all_completed:
            success, sparks_today, rank_up, old_rank, new_rank = add_spark(callback.from_user.id, 'categories')
            update_streak(callback.from_user.id)
            if success:
                # Бонусная искра если все категории >= 8
                today_ratings = get_today_ratings(callback.from_user.id)
                all_high = len(today_ratings) == 5 and all(v >= 8 for v in today_ratings.values())
                if all_high:
                    add_spark(callback.from_user.id, 'bonus_high')
                    await callback.answer("✨ Искра + бонус за отличный день!", show_alert=False)
                elif rank_up:
                    await callback.answer(f"✨ Новый ранг: {get_rank_name(new_rank)}!", show_alert=False)
                else:
                    await callback.answer("✨ Искра зачислена.", show_alert=False)
            # Все категории заполнены и оценка высокая — сразу в главное меню
            await delete_message_safe(bot, callback.message.chat.id, callback.message.message_id)
            await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
            await send_main_menu(bot, callback.from_user.id, callback.message.chat.id)
        else:
            # Не все категории заполнены — показываем рефлексию снова
            await delete_message_safe(bot, callback.message.chat.id, callback.message.message_id)
            await show_reflection_menu(callback.from_user.id, callback.message.chat.id, bot, state, callback.from_user.first_name)
    await callback.answer("✅ Сохранено!")



@router.callback_query(F.data.startswith("analyze_low:"))
async def analyze_low_rating_handler(callback: CallbackQuery, bot: Bot, state: FSMContext):
    category = callback.data.split(":")[1]
    today_ratings = get_today_ratings(callback.from_user.id)
    rating = today_ratings.get(category, 0)
    temps = user_temp_messages.get(callback.from_user.id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('low_rating'))
    all_filled_flag = temps.get('all_categories_filled', False)
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.TYPING)
    await asyncio.sleep(1)
    analysis = analyze_low_rating(callback.from_user.id, category, rating)
    if analysis.startswith("❌"):
        await state.update_data(
            retry_low_rating_category=category,
            retry_low_rating_value=rating,
            retry_action="low_rating"
        )
        await callback.message.answer(
            "❌ ИИ не ответил.",
            reply_markup=retry_ai_keyboard("low_rating")
        )
        if all_filled_flag:
            temps['all_categories_filled'] = True
        user_temp_messages[callback.from_user.id] = temps
        await callback.answer()
        return
    msg = await callback.message.answer(f"🤖 {analysis}", reply_markup=ai_reply_keyboard())
    temps['ai_response'] = msg.message_id
    if all_filled_flag:
        temps['all_categories_filled'] = True
    user_temp_messages[callback.from_user.id] = temps
    save_last_ai_answer(callback.from_user.id, analysis)
    await callback.answer()



@router.callback_query(F.data == "skip_analysis")
async def skip_analysis(callback: CallbackQuery, bot: Bot, state: FSMContext):
    temps = user_temp_messages.get(callback.from_user.id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('low_rating'))
    # Если все категории заполнены — сразу в главное меню
    if temps.get('all_categories_filled'):
        await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
        await send_main_menu(bot, callback.from_user.id, callback.message.chat.id)
    else:
        await show_reflection_menu(callback.from_user.id, callback.message.chat.id, bot, state, callback.from_user.first_name)
    await callback.answer()
