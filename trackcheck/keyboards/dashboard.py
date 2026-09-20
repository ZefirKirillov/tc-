from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.utils.formatting import days_left_str
from trackcheck.keyboards.common import with_back_kb


def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="📒 Рефлексия", callback_data="menu_reflection"),
         InlineKeyboardButton(text="⭐ Ранг", callback_data="menu_rank")],
        [InlineKeyboardButton(text="🏋️ Тренировки", callback_data="menu_workouts"),
         InlineKeyboardButton(text="Check AI", callback_data="menu_ai")],
        [InlineKeyboardButton(text="🍽 Диета", callback_data="menu_diet"),
         InlineKeyboardButton(text="📝 Задачи", callback_data="menu_tasks")]
    ]))



def urgent_tasks_keyboard(tasks: list, user_id: Optional[int] = None) -> Optional[InlineKeyboardMarkup]:
    """Инлайн-кнопки срочных задач для главного меню."""
    if not tasks:
        return None
    buttons = []
    for t in tasks:
        label = ("🔥 " if t['is_priority'] else "⏰ ") + t['title']
        if len(label) > 32:
            label = label[:29] + "..."
        if t.get('days_left') is not None:
            label += f" – {days_left_str(t['deadline'], user_id)}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"task_done_{t['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))
