import asyncio
import io
import math
import os
import re
from datetime import datetime

from aiogram import Bot, F
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from PIL import Image

from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    get_diet_profile, save_diet_profile, get_today_calories, get_today_food_log,
    save_food_log, save_weight_log, get_last_weight, save_body_fat, add_my_food,
    calculate_bmr, calculate_tdee, calculate_daily_calories,
)
from trackcheck.states.food import DietState
from trackcheck.services.ai_service import gemini_generate, analyze_food_photo
from trackcheck.services.tracker_service import sync_diet_rating_for_today
from trackcheck.services.chart_service import build_diet_chart
from trackcheck.utils.concurrency import run_in_thread
from trackcheck.utils.formatting import create_new_progress_bar
from trackcheck.utils.bot_helpers import (
    delete_message_safe, delete_temp_messages, delete_message_after_delay,
)
from trackcheck.keyboards.common import (
    with_back_kb, back_reply_keyboard, retry_ai_keyboard,
)
from trackcheck.keyboards.food import (
    diet_menu_reply_keyboard, meal_type_keyboard, meal_chosen_keyboard,
    save_food_keyboard, gender_keyboard, activity_keyboard,
    goal_keyboard, diet_confirm_keyboard, diet_confirm_food_keyboard,
    food_add_more_keyboard, food_cancel_keyboard,
)
from trackcheck.runtime import (user_temp_messages, user_last_menu,
                                user_food_history_page, nav_push)
from trackcheck.handlers import router


@router.callback_query(F.data == "menu_diet")
async def handle_diet(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    user_id = callback.from_user.id
    await state.clear()
    profile = get_diet_profile(user_id)
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[user_id] = None
    if not profile:
        await state.set_state(DietState.weight)
        await delete_temp_messages(bot, user_id, callback.message.chat.id, keep_ai=True)
        msg = await callback.message.answer("📝 Введи свой вес (в кг):",
                                             reply_markup=back_reply_keyboard())
        user_temp_messages.setdefault(user_id, {})['diet_setup'] = msg.message_id
        await callback.answer()
        return
    await delete_temp_messages(bot, user_id, callback.message.chat.id, keep_ai=True)
    await show_diet_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



async def show_diet_menu(user_id: int, chat_id: int, bot: Bot):
    profile = get_diet_profile(user_id)
    if not profile:
        return
    today_cal = get_today_calories(user_id)
    daily_goal = profile['daily_calories']
    percent = (today_cal / daily_goal * 100) if daily_goal > 0 else 0
    bar = create_new_progress_bar(int(percent//10), 10)

    food_log = get_today_food_log(user_id)
    food_lines = []
    for meal_type, desc, cal in food_log:
        food_lines.append(f"{meal_type}: {desc} ({int(cal)} ккал)")

    food_summary = "\n".join(food_lines) if food_lines else "Пока нет записей."

    text = f"""🍽 Меню диеты

Цель: {int(daily_goal)} ккал/день
Съедено сегодня: {int(today_cal)} ккал ({int(percent)}%)
{bar} {int(percent)}%

Сегодня:
{food_summary}

Выбери действие:"""
    msg = await bot.send_message(chat_id, text, reply_markup=diet_menu_reply_keyboard())
    nav_push(user_id, "diet")
    user_temp_messages.setdefault(user_id, {})['diet_menu'] = msg.message_id



@router.callback_query(F.data == "diet_food")
async def diet_log_food_reply(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await _diet_log_food_start(callback.from_user.id, callback.message.chat.id, bot, state)
    await callback.answer()



async def _diet_log_food_start(user_id: int, chat_id: int, bot: Bot, state: FSMContext):
    # Удаляем меню диеты
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.get('diet_menu'))
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, chat_id, old_menu)
        user_last_menu[user_id] = None
    await delete_temp_messages(bot, user_id, chat_id, keep_ai=True)
    await state.clear()
    await state.set_state(DietState.meal_type)
    msg = await bot.send_message(chat_id, "Выбери приём пищи:", reply_markup=meal_type_keyboard())
    user_temp_messages.setdefault(user_id, {})['diet_temp'] = msg.message_id
    nav_push(user_id, "diet_meal")



@router.callback_query(DietState.meal_type, F.data.startswith("meal_type:"))
async def diet_choose_meal(callback: CallbackQuery, bot: Bot, state: FSMContext):
    meal_map = {
        "Завтрак": "Завтрак",
        "Обед": "Обед",
        "Ужин": "Ужин",
        "Перекус": "Перекус"
    }
    meal_type = meal_map.get(callback.data.split(":", 1)[1])
    if not meal_type:
        await callback.answer()
        return
    await state.update_data(meal_type=meal_type)

    temps = user_temp_messages.get(callback.from_user.id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('diet_temp'))

    msg = await callback.message.answer(
        f"Приём пищи: <b>{meal_type}</b>\n\n"
        "Опиши что съел — ИИ посчитает калории, или запиши вручную:",
        parse_mode="HTML",
        reply_markup=meal_chosen_keyboard()
    )
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(DietState.meal_type, F.data == "meal_entry_manual")
async def meal_entry_manual(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('diet_temp'))
    await state.update_data(food_description='')
    await state.set_state(DietState.manual_calories)
    msg = await callback.message.answer(
        "✏️ Введи количество калорий (только число):",
        reply_markup=food_cancel_keyboard()
    )
    user_temp_messages.setdefault(user_id, {})['diet_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(DietState.meal_type, F.data == "meal_entry_cancel")
async def meal_entry_cancel(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, callback.message.chat.id, temps.get('diet_temp'))
    await state.clear()
    await callback.answer()
    await show_diet_menu(user_id, callback.message.chat.id, bot)



@router.message(DietState.meal_type, F.text & ~F.text.startswith("/"))
async def meal_type_text_forward(message: Message, bot: Bot, state: FSMContext):
    """Пользователь написал описание еды прямо после выбора приёма пищи — переключаем стейт и обрабатываем."""
    await state.set_state(DietState.food_description)
    await process_food_description(message, bot, state)



@router.message(DietState.meal_type, F.photo)
async def meal_type_photo_forward(message: Message, bot: Bot, state: FSMContext):
    """Пользователь отправил фото прямо после выбора приёма пищи."""
    await state.set_state(DietState.food_description)
    await process_food_photo(message, bot, state)



@router.callback_query(DietState.food_description, F.data.startswith("food_choose_"))
async def diet_choose_my_food(callback: CallbackQuery, bot: Bot, state: FSMContext):
    food_name = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id

    cursor = db.execute('SELECT calories FROM my_foods WHERE user_id = ? AND name = ?', (user_id, food_name))
    row = cursor.fetchone()
    if row:
        calories = row[0]
        await state.update_data(food_description=food_name, food_calories=calories)
        await callback.message.delete()
        await state.set_state(DietState.food_confirm)
        text = f"🍽 Ты съел: {food_name}\n🔢 Калории: {int(calories)} ккал\n\nВсё верно?"
        await callback.message.answer(text, reply_markup=diet_confirm_food_keyboard())
    else:
        await callback.answer("❌ Блюдо не найдено", show_alert=True)
        await _diet_log_food_start(callback.from_user.id, callback.message.chat.id, bot, state)
    await callback.answer()



@router.callback_query(DietState.food_description, F.data == "food_create_new")
async def diet_create_new_food(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await state.set_state(DietState.food_description)
    msg = await callback.message.answer(
        "🍽 Опиши, что ты съел, или отправь фото блюда:\n\n"
        "Или нажми /cancel для отмены.",
        reply_markup=food_cancel_keyboard()
    )
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(DietState.food_description, F.data == "food_cancel")
async def diet_cancel_food(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await show_diet_menu(callback.from_user.id, callback.message.chat.id, bot)
    await callback.answer()



@router.message(DietState.food_description, F.photo)
async def process_food_photo(message: Message, bot: Bot, state: FSMContext):
    """Оценка калорий по фото блюда."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    temps = user_temp_messages.get(user_id, {})
    # Удаляем служебное "Опиши что съел", фото юзера НЕ трогаем
    await delete_message_safe(bot, chat_id, temps.get('diet_temp'))

    wait_msg = await message.answer("🔍 Анализирую фото блюда...")
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    buffer = await bot.download_file(file.file_path)
    if buffer is None or not hasattr(buffer, 'read'):
        await wait_msg.edit_text("❌ Не удалось загрузить фото.")
        return
    if hasattr(buffer, 'seek'):
        buffer.seek(0)
    image = Image.open(buffer)
    img_buffer = io.BytesIO()
    image.save(img_buffer, format='PNG')
    image_bytes = img_buffer.getvalue()

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        await wait_msg.edit_text("❌ ИИ недоступен (нет API-ключа).")
        return
    prompt = """Посмотри на фото еды и оцени калорийность.

    Ответь строго в формате: [название блюда] [число ккал]
    Название — 1-4 слова на русском. Число — только целые ккал без единиц.

    Правила оценки:
    - Считай реальную порцию на фото, не занижай
    - Учитывай видимые соусы, масло, хлеб рядом
    - Если несколько блюд — суммируй всё

    Примеры правильных ответов:
    гречка с курицей 480
    паста карбонара 650
    омлет с сыром 350
    бургер и картошка 900
    салат цезарь 520"""
    # Сохраняем данные для повтора без повторной загрузки фото
    await state.update_data(
        retry_food_photo_bytes=image_bytes,
        retry_food_photo_prompt=prompt,
        retry_action="food_photo"
    )
    text = await run_in_thread(analyze_food_photo, image_bytes, prompt)
    if text is None:
        await wait_msg.edit_text(
            "❌ Ошибка анализа фото.\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("food_photo")
        )
        return

    description = "Блюдо на фото"
    calories = None
    nums = re.findall(r"\b(\d{2,5})\b", text)
    valid_nums = [float(n) for n in nums if 50 <= float(n) <= 9999]
    if valid_nums:
        calories = valid_nums[-1]  # берём последнее число — обычно итоговые ккал
    match = re.search(r"^([^0-9]+?)(?:\s*\d|$)", text)
    if match:
        desc = match.group(1).strip(" .,;:-")
        if 2 <= len(desc) <= 50:
            description = desc

    await delete_message_safe(bot, chat_id, wait_msg.message_id)
    if calories is None or calories <= 0 or calories > 5000:
        await state.update_data(food_description=description)
        await state.set_state(DietState.manual_calories)
        msg = await message.answer(
            f"🍽 Определено: {description}\n❌ Не удалось оценить калории. Введи вручную (число):",
            reply_markup=food_cancel_keyboard()
        )
        user_temp_messages.setdefault(user_id, {})['diet_temp'] = msg.message_id
        return

    await state.update_data(food_description=description, food_calories=calories)
    await state.set_state(DietState.food_confirm)
    await message.answer(
        f"🍽 Ты съел: {description}\n🔢 Калории: ~{int(calories)} ккал\n\nВсё верно?",
        reply_markup=diet_confirm_food_keyboard()
    )



@router.message(DietState.food_description, F.text)
async def process_food_description(message: Message, bot: Bot, state: FSMContext):
    description = message.text.strip()
    if len(description) < 3:
        temps = user_temp_messages.get(message.from_user.id, {})
        old_error = temps.get('diet_error')
        if old_error:
            await delete_message_safe(bot, message.chat.id, old_error)
        error_msg = await message.answer("❌ Слишком короткое описание. Попробуй ещё раз.")
        temps['diet_error'] = error_msg.message_id
        user_temp_messages[message.from_user.id] = temps
        return

    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    # Удаляем только служебное сообщение "Опиши что съел", сообщение юзера НЕ трогаем
    await delete_message_safe(bot, message.chat.id, temps.get('diet_temp'))
    if 'diet_error' in temps:
        await delete_message_safe(bot, message.chat.id, temps['diet_error'])
        del temps['diet_error']

    await bot.send_chat_action(message.chat.id, action=ChatAction.TYPING)
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
    await state.update_data(retry_food_description=description, retry_action="food_calories")
    response = await run_in_thread(gemini_generate, prompt, 100, True)
    try:
        numbers = re.findall(r"\b(\d{2,5})\b", response)
        numbers = [float(n) for n in numbers if 50 <= float(n) <= 9999]
        calories = numbers[-1] if numbers else None
    except:
        calories = None

    if calories is None or calories <= 0:
        await state.update_data(food_description=description)
        await state.set_state(DietState.manual_calories)
        msg = await message.answer(
            "❌ Не удалось определить калории автоматически. Нажми кнопку чтобы попробовать ещё раз.",
            reply_markup=retry_ai_keyboard("food_calories")
        )
        user_temp_messages.setdefault(user_id, {})['diet_temp'] = msg.message_id
        return

    await state.update_data(food_description=description, food_calories=calories)
    await state.set_state(DietState.food_confirm)
    text = f"🍽 Ты съел: {description}\n🔢 Калории: {int(calories)} ккал\n\nВсё верно?"
    await message.answer(text, reply_markup=diet_confirm_food_keyboard())



@router.callback_query(DietState.food_confirm, F.data == "food_confirm_yes")
async def food_confirm_yes(callback: CallbackQuery, bot: Bot, state: FSMContext):
    # Убираем только кнопки, само сообщение с калориями остаётся
    await callback.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    meal_type = data.get('meal_type')
    description = data.get('food_description')
    calories = data.get('food_calories')
    user_id = callback.from_user.id
    save_food_log(user_id, meal_type, description, calories)
    asyncio.create_task(run_in_thread(sync_diet_rating_for_today, user_id))

    success_msg = await callback.message.answer(f"✅ Записано: {int(calories)} ккал.")
    await asyncio.sleep(2)
    await delete_message_safe(bot, callback.message.chat.id, success_msg.message_id)

    await state.set_state(DietState.food_confirm)
    question_msg = await callback.message.answer(
        "Хочешь добавить ещё запись?",
        reply_markup=food_add_more_keyboard()
    )
    asyncio.create_task(delete_message_after_delay(
        bot, callback.message.chat.id, question_msg.message_id, delay=10
    ))



@router.callback_query(F.data == "food_add_more_yes")
async def food_add_more(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(DietState.meal_type)
    await callback.message.delete()
    msg = await callback.message.answer("Выбери приём пищи:", reply_markup=meal_type_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await callback.answer()



@router.callback_query(DietState.food_confirm, F.data == "food_confirm_redo")
async def food_confirm_redo(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(DietState.meal_type)
    chat_id = callback.message.chat.id
    await callback.message.edit_reply_markup(reply_markup=None)
    msg = await bot.send_message(chat_id, "Выбери приём пищи:", reply_markup=meal_type_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await callback.message.delete()
    await callback.answer()



@router.callback_query(DietState.food_confirm, F.data == "food_confirm_manual")
async def food_confirm_manual(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.set_state(DietState.manual_calories)
    chat_id = callback.message.chat.id
    await callback.message.edit_reply_markup(reply_markup=None)
    msg = await bot.send_message(chat_id, "✏️ Введи количество калорий вручную (только число):", reply_markup=food_cancel_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await callback.message.delete()
    await callback.answer()



@router.message(DietState.manual_calories)
async def manual_calories(message: Message, bot: Bot, state: FSMContext):
    import math
    try:
        calories = float((message.text or "").strip().replace(',', '.'))
        if not math.isfinite(calories) or calories <= 0 or calories > 10000:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введи корректное число калорий (например, 350):")
        return

    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('diet_temp'))

    data = await state.get_data()
    meal_type = data.get('meal_type')
    description = data.get('food_description', '')
    save_food_log(user_id, meal_type, description, calories)
    asyncio.create_task(run_in_thread(sync_diet_rating_for_today, user_id))

    await state.update_data(manual_calories_value=calories)
    await state.set_state(DietState.new_food_name)
    msg = await message.answer(
        f"✅ Записано: {int(calories)} ккал\n\nСохранить в «Мои блюда»?",
        reply_markup=save_food_keyboard()
    )
    user_temp_messages.setdefault(user_id, {})['diet_temp'] = msg.message_id



@router.callback_query(DietState.new_food_name, F.data == "save_food_skip")
async def save_food_skip(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    calories = data.get('manual_calories_value')
    await callback.message.delete()
    await state.clear()
    temp_msg = await callback.message.answer(f"✅ Записано: {int(calories)} ккал.")
    await asyncio.sleep(2)
    await delete_message_safe(bot, callback.message.chat.id, temp_msg.message_id)
    await show_diet_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(DietState.new_food_name, F.data == "save_food_yes")
async def save_food_yes_prompt(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    msg = await callback.message.answer("Введи название блюда для сохранения:",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await state.update_data(awaiting_food_name_input=True)
    await callback.answer()



@router.message(DietState.new_food_name, F.text)
async def save_my_food_name(message: Message, bot: Bot, state: FSMContext):
    name = message.text.strip()
    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('diet_temp'))

    data = await state.get_data()
    calories = data.get('manual_calories_value')

    add_my_food(user_id, name, calories)
    success_msg = await message.answer(f"✅ Блюдо «{name}» сохранено в Мои блюда.")
    await asyncio.sleep(2)
    await delete_message_safe(bot, message.chat.id, success_msg.message_id)

    await state.clear()
    temp_msg = await message.answer(f"✅ Записано: {int(calories)} ккал.")
    await asyncio.sleep(2)
    await delete_message_safe(bot, message.chat.id, temp_msg.message_id)
    await show_diet_menu(user_id, message.chat.id, bot)



@router.callback_query(F.data == "food_cancel")
async def food_cancel(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await show_diet_menu(callback.from_user.id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(F.data == "diet_weight")
async def diet_log_weight_reply(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    old_menu = user_last_menu.get(callback.from_user.id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[callback.from_user.id] = None
    await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
    await state.clear()
    await state.set_state(DietState.log_weight)
    msg = await callback.message.answer("⚖️ Введи свой текущий вес (в кг):",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await callback.answer()



@router.message(DietState.log_weight)
async def diet_log_weight_finish(message: Message, bot: Bot, state: FSMContext):
    try:
        weight = float((message.text or "").strip().replace(',', '.'))
        if not math.isfinite(weight) or weight < 20 or weight > 300:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введи корректный вес (например, 70.5):")
        return

    user_id = message.from_user.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, message.chat.id, message.message_id)
    await delete_message_safe(bot, message.chat.id, temps.get('diet_temp'))

    last_weight = get_last_weight(user_id)
    save_weight_log(user_id, weight)

    profile = get_diet_profile(user_id)
    motivation = ""
    if last_weight:
        diff = weight - last_weight
        if profile and profile['goal_type'] == 'loss':
            if diff < 0:
                motivation = f"\n✅ Отлично! Ты похудел на {abs(diff):.1f} кг. Так держать!"
            elif diff > 0:
                motivation = f"\n⚠️ Вес увеличился на {diff:.1f} кг. Не сдавайся, продолжай следить за питанием!"
            else:
                motivation = "\n👌 Вес не изменился. Держим уровень!"
        elif profile and profile['goal_type'] == 'gain':
            if diff > 0:
                motivation = f"\n✅ Отлично! Ты набрал {diff:.1f} кг. Прогресс!"
            elif diff < 0:
                motivation = f"\n⚠️ Вес уменьшился на {abs(diff):.1f} кг. Поднажми с питанием!"
            else:
                motivation = "\n👌 Вес не изменился."
        else:
            if abs(diff) < 1:
                motivation = "\n👍 Вес стабилен. Отлично!"
            elif diff > 0:
                motivation = f"\n📈 Вес вырос на {diff:.1f} кг. Если это не входило в планы, обрати внимание."
            else:
                motivation = f"\n📉 Вес снизился на {abs(diff):.1f} кг."

    await state.clear()
    success_msg = await message.answer(f"✅ Вес {weight} кг записан." + motivation)
    await asyncio.sleep(3)
    await delete_message_safe(bot, message.chat.id, success_msg.message_id)
    await show_diet_menu(user_id, message.chat.id, bot)



@router.callback_query(F.data == "diet_bodyfat")
async def diet_body_fat_reply(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    old_menu = user_last_menu.get(callback.from_user.id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[callback.from_user.id] = None
    await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
    await state.clear()
    instructions = (
        "Введи свои данные в одной строке через пробел:\n"
        "рост(см) вес(кг) обхват шеи(см) обхват талии(см) [обхват бёдер(см) для женщин]\n\n"
        "Пример для мужчины: 175 70 40 80\n"
        "Пример для женщины: 165 60 38 70 95"
    )
    await state.set_state(DietState.body_fat_measurements)
    msg = await callback.message.answer(instructions, reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_temp'] = msg.message_id
    await callback.answer()



@router.message(DietState.body_fat_measurements)
async def diet_body_fat_calculate(message: Message, bot: Bot, state: FSMContext):
    temps = user_temp_messages.get(message.from_user.id, {})
    error_msg_id = temps.get('body_fat_error')
    if error_msg_id:
        await delete_message_safe(bot, message.chat.id, error_msg_id)
        del temps['body_fat_error']
        user_temp_messages[message.from_user.id] = temps

    parts = (message.text or "").strip().split()
    user_id = message.from_user.id

    if len(parts) not in (4, 5):
        error_msg = await message.answer("❌ Неверное количество чисел. Должно быть 4 (мужчины) или 5 (женщины).")
        temps['body_fat_error'] = error_msg.message_id
        user_temp_messages[user_id] = temps
        return

    try:
        numbers = [float(p.replace(',', '.')) for p in parts]
        if not all(math.isfinite(n) and n > 0 for n in numbers):
            raise ValueError
    except ValueError:
        error_msg = await message.answer("❌ Неверный формат чисел. Используй точки или запятые.")
        temps['body_fat_error'] = error_msg.message_id
        user_temp_messages[user_id] = temps
        return

    # Сохраняем сообщение пользователя с замерами (не удаляем)
    temps['body_fat_measurements'] = message.message_id
    user_temp_messages[user_id] = temps

    height_cm = numbers[0]
    weight = numbers[1]
    neck = numbers[2]
    waist = numbers[3]
    hip = numbers[4] if len(numbers) == 5 else None

    if hip is not None:  # женщина
        height_inch = height_cm * 0.393701
        diff = waist + hip - neck
        if diff <= 0:
            error_msg = await message.answer("❌ Сумма обхватов талии и бёдер должна быть больше обхвата шеи.")
            temps['body_fat_error'] = error_msg.message_id
            user_temp_messages[user_id] = temps
            return
        body_fat = 163.205 * math.log10(diff) - 97.684 * math.log10(height_inch) + 104.912
    else:  # мужчина — YMCA
        waist_inch = waist / 2.54
        weight_lb = weight * 2.20462
        body_fat = -98.42 + 4.15 * waist_inch - 0.082 * weight_lb
        if body_fat < 3:
            body_fat = 3.0
        elif body_fat > 50:
            body_fat = 50.0

    body_fat = round(body_fat, 2)
    warning = ""
    if body_fat < 2 or body_fat > 70:
        warning = f"\n⚠️ Результат ({body_fat}%) кажется необычным. Проверь измерения."

    # НЕ удаляем сообщение пользователя с замерами
    await delete_message_safe(bot, message.chat.id, temps.get('diet_temp'))

    save_body_fat(user_id, body_fat)
    await state.clear()
    success_msg = await message.answer(f"🧮 Процент жира: **{body_fat}%**{warning}", parse_mode="Markdown")
    # Сохраняем результат для возможного удаления позже
    temps['body_fat_result'] = success_msg.message_id
    user_temp_messages[user_id] = temps
    await show_diet_menu(user_id, message.chat.id, bot)



@router.callback_query(F.data == "diet_food_history")
async def diet_food_history_reply(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    old_menu = user_last_menu.get(callback.from_user.id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[callback.from_user.id] = None
    await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
    user_id = callback.from_user.id
    user_food_history_page[user_id] = 0
    await show_food_history_page(user_id, callback.message.chat.id, bot, state)
    await callback.answer()



async def show_food_history_page(user_id: int, chat_id: int, bot: Bot, state: FSMContext, edit_message_id: int = None):
    page = user_food_history_page.get(user_id, 0)
    limit_days = 3
    offset_days = page * limit_days

    cursor = db.execute('''
        SELECT DISTINCT date
        FROM diet_log
        WHERE user_id = ?
        ORDER BY date DESC
    ''', (user_id,))
    all_dates = [row[0] for row in cursor.fetchall()]
    total_days = len(all_dates)
    total_pages = (total_days + limit_days - 1) // limit_days if total_days > 0 else 1

    if page >= total_pages and total_pages > 0:
        user_food_history_page[user_id] = total_pages - 1
        page = total_pages - 1
        offset_days = page * limit_days

    if total_days == 0:
        text = "📖 История еды пока пуста."
    else:
        start_idx = offset_days
        end_idx = min(offset_days + limit_days, total_days)
        page_dates = all_dates[start_idx:end_idx]

        lines = []
        for date in page_dates:
            food_cursor = db.execute('''
                SELECT meal_type, food_description, calories
                FROM diet_log
                WHERE user_id = ? AND date = ?
                ORDER BY timestamp
            ''', (user_id, date))
            day_foods = food_cursor.fetchall()
            formatted_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d.%m.%Y')
            lines.append(f"\n📅 {formatted_date}")
            total_day_cal = 0
            for meal, desc, cal in day_foods:
                lines.append(f"  {meal}: {desc} ({int(cal)} ккал)")
                total_day_cal += cal
            lines.append(f"  🔥 Итого за день: {int(total_day_cal)} ккал")
        text = "📖 История еды\n" + "\n".join(lines)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущая", callback_data="food_history_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Следующая ➡️", callback_data="food_history_next"))

    keyboard_buttons = []
    if nav_buttons:
        keyboard_buttons.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(inline_keyboard=with_back_kb(keyboard_buttons))

    if edit_message_id:
        await bot.edit_message_text(text, chat_id, edit_message_id, reply_markup=reply_markup)
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        user_temp_messages.setdefault(user_id, {})['food_history'] = msg.message_id
    nav_push(user_id, "food_history")



@router.callback_query(F.data == "food_history_prev")
async def food_history_prev(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    page = user_food_history_page.get(user_id, 0)
    if page > 0:
        user_food_history_page[user_id] = page - 1
    await show_food_history_page(user_id, callback.message.chat.id, bot, state, edit_message_id=callback.message.message_id)
    await callback.answer()



@router.callback_query(F.data == "food_history_next")
async def food_history_next(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    page = user_food_history_page.get(user_id, 0)
    user_food_history_page[user_id] = page + 1
    await show_food_history_page(user_id, callback.message.chat.id, bot, state, edit_message_id=callback.message.message_id)
    await callback.answer()



@router.callback_query(F.data == "back_to_diet")
async def back_to_diet(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await show_diet_menu(callback.from_user.id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(F.data == "diet_charts")
async def diet_charts_reply(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    old_menu = user_last_menu.get(callback.from_user.id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[callback.from_user.id] = None
    await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
    user_id = callback.from_user.id
    await bot.send_chat_action(callback.message.chat.id, action=ChatAction.UPLOAD_PHOTO)

    cursor = db.execute('SELECT date, weight FROM weight_log WHERE user_id = ? ORDER BY date', (user_id,))
    weight_rows = cursor.fetchall()
    bf_cursor = db.execute('SELECT date, body_fat FROM body_fat_log WHERE user_id = ? ORDER BY date', (user_id,))
    fat_rows = bf_cursor.fetchall()

    if len(weight_rows) < 2 and len(fat_rows) < 2:
        err = await callback.message.answer("❌ Недостаточно данных для графиков (нужно минимум 2 записи по весу или % жира).")
        await asyncio.sleep(4)
        await delete_message_safe(bot, callback.message.chat.id, err.message_id)
        await show_diet_menu(user_id, callback.message.chat.id, bot)
        await callback.answer()
        return

    chart_path = await run_in_thread(build_diet_chart, user_id, weight_rows, fat_rows)
    if chart_path is None:
        err = await callback.message.answer("❌ Недостаточно данных для графиков (нужно минимум 2 записи по весу или % жира).")
        await asyncio.sleep(4)
        await delete_message_safe(bot, callback.message.chat.id, err.message_id)
        await show_diet_menu(user_id, callback.message.chat.id, bot)
        await callback.answer()
        return
    try:
        photo = FSInputFile(chart_path)
        await bot.send_photo(
            user_id,
            photo,
            caption="📈 Динамика веса и % жира"
        )
    finally:
        try:
            os.remove(chart_path)
        except OSError:
            pass



@router.callback_query(F.data == "diet_goal")
async def diet_change_goal_reply(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    old_menu = user_last_menu.get(callback.from_user.id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[callback.from_user.id] = None
    await delete_temp_messages(bot, callback.from_user.id, callback.message.chat.id, keep_ai=True)
    await state.clear()
    await state.set_state(DietState.weight)
    msg = await callback.message.answer("📝 Введи свой вес (в кг):",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_setup'] = msg.message_id
    await callback.answer()



@router.message(DietState.weight)
async def diet_step_weight(message: Message, bot: Bot, state: FSMContext):
    try:
        weight = float((message.text or "").strip().replace(',', '.'))
        if not math.isfinite(weight) or not 20 <= weight <= 300:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введи корректный вес (например, 75.5):")
        return
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(message.from_user.id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('diet_setup'))
    await state.update_data(weight=weight)
    await state.set_state(DietState.height)
    msg = await message.answer("📝 Введи свой рост (в см):",
                                reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(message.from_user.id, {})['diet_setup'] = msg.message_id



@router.message(DietState.height)
async def diet_step_height(message: Message, bot: Bot, state: FSMContext):
    try:
        height = float((message.text or "").strip().replace(',', '.'))
        if not math.isfinite(height) or not 100 <= height <= 250:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введи корректный рост (например, 175):")
        return
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(message.from_user.id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('diet_setup'))
    await state.update_data(height=height)
    await state.set_state(DietState.age)
    msg = await message.answer("📝 Введи свой возраст (лет):",
                                reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(message.from_user.id, {})['diet_setup'] = msg.message_id



@router.message(DietState.age)
async def diet_step_age(message: Message, bot: Bot, state: FSMContext):
    try:
        age = int((message.text or "").strip())
        if not 10 <= age <= 120:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введи корректный возраст (например, 25):")
        return
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(message.from_user.id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('diet_setup'))
    await state.update_data(age=age)
    await state.set_state(DietState.gender)
    msg = await message.answer("👤 Укажи пол:", reply_markup=gender_keyboard())
    user_temp_messages.setdefault(message.from_user.id, {})['diet_setup'] = msg.message_id



@router.callback_query(DietState.gender, F.data.in_({"gender_male", "gender_female"}))
async def diet_step_gender(callback: CallbackQuery, bot: Bot, state: FSMContext):
    gender = "мужской" if callback.data == "gender_male" else "женский"
    await callback.message.delete()
    await state.update_data(gender=gender)
    await state.set_state(DietState.activity)
    msg = await callback.message.answer("🏃 Выбери уровень активности:", reply_markup=activity_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_setup'] = msg.message_id
    await callback.answer()



@router.callback_query(DietState.activity, F.data.startswith("activity_"))
async def diet_step_activity(callback: CallbackQuery, bot: Bot, state: FSMContext):
    try:
        activity_level = float(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка выбора", show_alert=True)
        return
    await callback.message.delete()
    await state.update_data(activity_level=activity_level)
    await state.set_state(DietState.goal)
    msg = await callback.message.answer("🎯 Выбери цель:", reply_markup=goal_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['diet_setup'] = msg.message_id
    await callback.answer()



@router.callback_query(DietState.goal, F.data.in_({"goal_loss", "goal_maintain", "goal_gain"}))
async def diet_step_goal(callback: CallbackQuery, bot: Bot, state: FSMContext):
    goal_map = {"goal_loss": "loss", "goal_maintain": "maintain", "goal_gain": "gain"}
    goal_type = goal_map[callback.data]
    await callback.message.delete()
    await state.update_data(goal_type=goal_type)
    if goal_type == "maintain":
        await state.update_data(target_weight_change=0.0, target_days=30)
        await state.set_state(DietState.confirm)
        await _show_diet_confirm(callback.message, callback.from_user.id, state)
    else:
        await state.set_state(DietState.target_weight)
        direction = "сбросить" if goal_type == "loss" else "набрать"
        msg = await callback.message.answer(f"⚖️ Сколько кг хочешь {direction}? (например, 5):",
                                             reply_markup=back_reply_keyboard())
        user_temp_messages.setdefault(callback.from_user.id, {})['diet_setup'] = msg.message_id
    await callback.answer()



@router.message(DietState.target_weight)
async def diet_step_target_weight(message: Message, bot: Bot, state: FSMContext):
    try:
        change = float((message.text or "").strip().replace(',', '.'))
        if not math.isfinite(change) or not 0.1 <= change <= 100:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введи число (например, 5):")
        return
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(message.from_user.id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('diet_setup'))
    await state.update_data(target_weight_change=change)
    await state.set_state(DietState.target_days)
    msg = await message.answer("📅 За сколько дней хочешь достичь цели? (например, 90):",
                                reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(message.from_user.id, {})['diet_setup'] = msg.message_id



@router.message(DietState.target_days)
async def diet_step_target_days(message: Message, bot: Bot, state: FSMContext):
    try:
        days = int((message.text or "").strip())
        if not 7 <= days <= 730:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Введи число дней от 7 до 730:")
        return
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(message.from_user.id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('diet_setup'))
    await state.update_data(target_days=days)
    await state.set_state(DietState.confirm)
    await _show_diet_confirm(message, message.from_user.id, state)



async def _show_diet_confirm(message, user_id: int, state: FSMContext):
    data = await state.get_data()
    weight = data.get('weight')
    height = data.get('height')
    age = data.get('age')
    gender = data.get('gender')
    activity_level = data.get('activity_level')
    goal_type = data.get('goal_type')
    target_change = data.get('target_weight_change', 0.0)
    target_days = data.get('target_days', 30)

    bmr = calculate_bmr(weight, height, age, gender)
    tdee = calculate_tdee(bmr, activity_level)
    daily_calories, warning = calculate_daily_calories(tdee, goal_type, target_change, target_days, gender)

    goal_label = {"loss": "Снижение веса", "maintain": "Поддержание веса", "gain": "Набор массы"}.get(goal_type, goal_type)
    activity_labels = {1.2: "Сидячий", 1.375: "Лёгкий", 1.55: "Умеренный", 1.725: "Высокий", 1.9: "Очень высокий"}
    activity_label = activity_labels.get(activity_level, str(activity_level))

    text = f"""📋 Проверь данные:

👤 Вес: {weight} кг | Рост: {height} см | Возраст: {age} лет
🚻 Пол: {gender} | Активность: {activity_label}
🎯 Цель: {goal_label}"""
    if goal_type != "maintain":
        text += f"\n⚖️ Изменение: {target_change} кг за {target_days} дней"
    text += f"\n\n🔥 Норма калорий: <b>{int(daily_calories)} ккал/день</b>"
    if warning != "ok":
        text += f"\n\n{warning}"
    text += "\n\nВсё верно?"

    await state.update_data(daily_calories=daily_calories)
    msg = await message.answer(text, parse_mode="HTML", reply_markup=diet_confirm_keyboard())
    user_temp_messages.setdefault(user_id, {})['diet_setup'] = msg.message_id



@router.callback_query(DietState.confirm, F.data == "diet_confirm")
async def diet_step_confirm(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    await callback.message.delete()
    save_diet_profile(
        user_id=user_id,
        weight=data['weight'],
        height=data['height'],
        age=data['age'],
        gender=data['gender'],
        activity_level=data['activity_level'],
        goal_type=data['goal_type'],
        target_weight_change=data.get('target_weight_change', 0.0),
        target_days=data.get('target_days', 30),
        daily_calories=data['daily_calories']
    )
    await state.clear()
    success_msg = await callback.message.answer("✅ Профиль сохранён!")
    await asyncio.sleep(2)
    await delete_message_safe(bot, callback.message.chat.id, success_msg.message_id)
    await show_diet_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(DietState.confirm, F.data == "diet_restart")
async def diet_step_restart(callback: CallbackQuery, bot: Bot, state: FSMContext):
    user_id = callback.from_user.id
    await callback.message.delete()
    await state.clear()
    await state.set_state(DietState.weight)
    msg = await callback.message.answer("📝 Введи свой вес (в кг):",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(user_id, {})['diet_setup'] = msg.message_id
    await callback.answer()
