from typing import List, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.keyboards.common import with_back_kb


def diet_menu_reply_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🍎 Записать еду", callback_data="diet_food"),
         InlineKeyboardButton(text="⚖️ Записать вес", callback_data="diet_weight")],
        [InlineKeyboardButton(text="🧮 Рассчитать % жира", callback_data="diet_bodyfat"),
         InlineKeyboardButton(text="📖 История еды", callback_data="diet_food_history")],
        [InlineKeyboardButton(text="📈 Графики веса и % жира", callback_data="diet_charts"),
         InlineKeyboardButton(text="⚙️ Изменить цель", callback_data="diet_goal")]
    ]))



def meal_type_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🍳 Завтрак", callback_data="meal_type:Завтрак"),
         InlineKeyboardButton(text="🥗 Обед", callback_data="meal_type:Обед")],
        [InlineKeyboardButton(text="🍽 Ужин", callback_data="meal_type:Ужин"),
         InlineKeyboardButton(text="🍪 Перекус", callback_data="meal_type:Перекус")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="meal_entry_cancel")]
    ]))
    return keyboard



def meal_chosen_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✏️ Записать калории вручную", callback_data="meal_entry_manual")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="meal_entry_cancel")]
    ]))



def save_food_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="💾 Сохранить в «Мои блюда»", callback_data="save_food_yes")],
        [InlineKeyboardButton(text="➡️ Пропустить", callback_data="save_food_skip")]
    ]))



def my_foods_keyboard(foods: List[Tuple[str, float]]):
    buttons = []
    for name, calories in foods:
        buttons.append([InlineKeyboardButton(text=f"{name} ({int(calories)} ккал)", callback_data=f"food_choose_{name}")])
    buttons.append([InlineKeyboardButton(text="➕ Создать новое блюдо", callback_data="food_create_new")])
    buttons.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="food_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))



def gender_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🚹 Мужской", callback_data="gender_male"),
         InlineKeyboardButton(text="🚺 Женский", callback_data="gender_female")]
    ]))
    return keyboard



def activity_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="1️⃣ Сидячий (нет тренировок)", callback_data="activity_1.2")],
        [InlineKeyboardButton(text="2️⃣ Лёгкий (1-3 раза/нед)", callback_data="activity_1.375")],
        [InlineKeyboardButton(text="3️⃣ Умеренный (3-5 раз/нед)", callback_data="activity_1.55")],
        [InlineKeyboardButton(text="4️⃣ Высокий (6-7 раз/нед)", callback_data="activity_1.725")],
        [InlineKeyboardButton(text="5️⃣ Очень высокий (физ. работа + спорт)", callback_data="activity_1.9")]
    ]))
    return keyboard



def goal_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🔻 Снизить вес", callback_data="goal_loss")],
        [InlineKeyboardButton(text="🔹 Поддерживать вес", callback_data="goal_maintain")],
        [InlineKeyboardButton(text="🔺 Набрать вес", callback_data="goal_gain")]
    ]))
    return keyboard



def diet_confirm_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="diet_confirm")],
        [InlineKeyboardButton(text="🔄 Заново", callback_data="diet_restart")]
    ]))
    return keyboard



def diet_confirm_food_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✅ Да, верно", callback_data="food_confirm_yes")],
        [InlineKeyboardButton(text="🔄 Ввести заново", callback_data="food_confirm_redo")],
        [InlineKeyboardButton(text="✏️ Ввести калории вручную", callback_data="food_confirm_manual")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="food_cancel")]
    ]))
    return keyboard



def food_add_more_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✅ Да, добавить ещё", callback_data="food_add_more_yes")],
        [InlineKeyboardButton(text="❌ Нет, в меню", callback_data="back_to_main")]
    ]))
    return keyboard



def food_cancel_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="❌ Отмена", callback_data="food_cancel")]
    ]))
    return keyboard
