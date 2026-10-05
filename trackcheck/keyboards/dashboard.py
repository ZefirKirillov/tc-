from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from trackcheck.config import MINIAPP_URL
from trackcheck.utils.formatting import days_left_str


def open_app_button(text: str = "🚀 Открыть приложение") -> InlineKeyboardButton:
    """Deep-link button into the Mini App. Used across section menus."""
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=MINIAPP_URL))


def main_menu_keyboard():
    # Главное меню — корневой экран: кнопки «Назад» здесь нет (возвращаться некуда).
    # Mini App — главный способ работы с TrackCheck, поэтому кнопка первой.
    return InlineKeyboardMarkup(inline_keyboard=[
        [open_app_button("🚀 Открыть TrackCheck")],
        [InlineKeyboardButton(text="📒 Рефлексия", callback_data="menu_reflection"),
         InlineKeyboardButton(text="⭐ Ранг", callback_data="menu_rank")],
        [InlineKeyboardButton(text="🏋️ Тренировки", callback_data="menu_workouts"),
         InlineKeyboardButton(text="Check AI", callback_data="menu_ai")],
        [InlineKeyboardButton(text="🍽 Диета", callback_data="menu_diet"),
         InlineKeyboardButton(text="📝 Задачи", callback_data="menu_tasks")],
    ])



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
    return InlineKeyboardMarkup(inline_keyboard=buttons)
