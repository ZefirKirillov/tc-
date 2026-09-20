from typing import List, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.keyboards.common import with_back_kb, _back_button_row


def workout_main_reply_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🏋️ Добавить выполнение", callback_data="menu_workout_add"),
         InlineKeyboardButton(text="🤳 Анализ фото", callback_data="menu_photo_analysis")],
        [InlineKeyboardButton(text="📋 Управление", callback_data="menu_workout_manage"),
         InlineKeyboardButton(text="📊 История", callback_data="workout_history")]
    ]))



def workout_manage_reply_keyboard(mode: str = "ai"):
    """Клавиатура управления планом."""
    rows = [
        [InlineKeyboardButton(text="🆕 Новый план (ИИ)", callback_data="wp_new_plan"),
         InlineKeyboardButton(text="📝 Загрузить свой план", callback_data="wp_mode_manual")]
    ]
    if mode == "ai":
        rows.insert(0, [InlineKeyboardButton(text="✏️ Редактировать план (ИИ)", callback_data="wp_edit_plan")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(rows))



def workout_main_keyboard():
    return workout_main_reply_keyboard()



def workout_categories_keyboard(categories: List[Tuple[int, str]], action: str = "add"):
    buttons = []
    row = []
    for i, (cat_id, cat_name) in enumerate(categories):
        if action == "add":
            callback = f"w_add_cat_{cat_id}"
        else:
            callback = f"w_manage_cat_{cat_id}"
        row.append(InlineKeyboardButton(text=cat_name, callback_data=callback))
        if len(row) == 2 or i == len(categories)-1:
            buttons.append(row)
            row = []
    if action == "manage":
        buttons.append([InlineKeyboardButton(text="➕ Создать категорию", callback_data="w_cat_new")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))



def workout_category_actions_keyboard(cat_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="📋 Упражнения", callback_data=f"w_manage_exercises_{cat_id}")],
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"w_cat_rename_{cat_id}"),
         InlineKeyboardButton(text="❌ Удалить", callback_data=f"w_cat_delete_{cat_id}")]
    ]))
    return keyboard



def workout_exercises_keyboard(exercises: List[Tuple[int, str]], cat_id: int, action: str = "add"):
    buttons = []
    row = []
    for i, (ex_id, ex_name) in enumerate(exercises):
        if action == "add":
            callback = f"w_add_ex_{ex_id}"
        else:
            callback = f"w_manage_ex_{ex_id}"
        row.append(InlineKeyboardButton(text=ex_name, callback_data=callback))
        if len(row) == 2 or i == len(exercises)-1:
            buttons.append(row)
            row = []
    if action == "manage":
        buttons.append([InlineKeyboardButton(text="➕ Создать упражнение", callback_data=f"w_ex_new_{cat_id}")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))



def workout_exercise_actions_keyboard(ex_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"w_ex_rename_{ex_id}"),
         InlineKeyboardButton(text="❌ Удалить", callback_data=f"w_ex_delete_{ex_id}")],
        [InlineKeyboardButton(text="🎯 Установить цель", callback_data=f"w_ex_set_goal_{ex_id}")]
    ]))
    return keyboard



def workout_continue_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✅ Добавить ещё", callback_data="w_continue_yes")],
        [InlineKeyboardButton(text="❌ Закончить", callback_data="workout_main")]
    ]))
    return keyboard



def workout_exercise_goal_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🎯 Силовое", callback_data="goal_strength")],
        [InlineKeyboardButton(text="🚴 Кардио", callback_data="goal_cardio")]
    ]))
    return keyboard



def workout_action_choice_keyboard(ex_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="📝 Ввести вручную", callback_data=f"w_manual_{ex_id}")],
        [InlineKeyboardButton(text="🎯 Цель достигнута", callback_data=f"w_achieve_goal_{ex_id}")]
    ]))
    return keyboard



def wp_mode_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🤖 Создать план с ИИ", callback_data="wp_mode_ai")],
        [InlineKeyboardButton(text="📝 Ввести свой план", callback_data="wp_mode_manual")]
    ]))



def wp_goal_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="💪 Набор массы", callback_data="wp_goal_mass")],
        [InlineKeyboardButton(text="🔥 Похудение", callback_data="wp_goal_loss")],
        [InlineKeyboardButton(text="⚡ Сила", callback_data="wp_goal_strength")],
        [InlineKeyboardButton(text="🎯 Общая форма", callback_data="wp_goal_fitness")]
    ]))



def wp_level_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🌱 Новичок", callback_data="wp_level_beginner")],
        [InlineKeyboardButton(text="📈 Средний", callback_data="wp_level_intermediate")],
        [InlineKeyboardButton(text="🏆 Продвинутый", callback_data="wp_level_advanced")]
    ]))



def wp_days_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="2", callback_data="wp_days_2"),
         InlineKeyboardButton(text="3", callback_data="wp_days_3"),
         InlineKeyboardButton(text="4", callback_data="wp_days_4"),
         InlineKeyboardButton(text="5", callback_data="wp_days_5")]
    ]))



def wp_plan_review_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✅ Принять план", callback_data="wp_plan_accept")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="wp_plan_edit")],
        [InlineKeyboardButton(text="🔄 Сгенерировать заново", callback_data="wp_plan_regenerate")]
    ]))



def wp_plan_review_keyboard_manual():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✅ Принять план", callback_data="wp_plan_accept")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="wp_plan_edit")],
        [InlineKeyboardButton(text="🔄 Ввести заново", callback_data="wp_mode_manual")]
    ]))



def wp_edit_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[_back_button_row()])



def ws_today_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="ПОГНАЛИ 💪", callback_data="ws_start")],
        [InlineKeyboardButton(text="Пропустил день", callback_data="ws_skip_day")]
    ]))



def ws_exercise_keyboard(is_first: bool = True):
    buttons = [
        [InlineKeyboardButton(text="✅ Цель выполнена", callback_data="ws_ex_done")],
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="ws_ex_skip")]
    ]
    if not is_first:
        buttons.append([InlineKeyboardButton(text="↩️ Предыдущее упражнение", callback_data="ws_ex_prev")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))



def ws_skip_day_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[_back_button_row()])



def ws_rest_day_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[_back_button_row()])



def wp_settings_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🔄 Обновить план", callback_data="wp_reset")],
        [InlineKeyboardButton(text="📋 Пересмотр упражнений", callback_data="wp_monthly_review")]
    ]))



def wp_monthly_review_keyboard(changes: list):
    buttons = []
    for i, ch in enumerate(changes):
        buttons.append([InlineKeyboardButton(
            text=f"{i+1}. {ch['old_exercise']} → {ch['new_exercise']}",
            callback_data=f"wp_review_noop"
        )])
    buttons.append([InlineKeyboardButton(text="✅ Принять выбранные", callback_data="wp_review_accept")])
    buttons.append([InlineKeyboardButton(text="❌ Отклонить всё", callback_data="wp_review_decline")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))



def workout_ai_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="📋 Настройки плана", callback_data="wp_settings")]
    ]))
