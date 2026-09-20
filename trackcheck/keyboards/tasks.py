from typing import Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.utils.formatting import days_left_str
from trackcheck.keyboards.common import with_back_kb


def tasks_menu_keyboard(tasks: list, user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    buttons = []
    for t in tasks:
        prefix = "🔥 " if t['is_priority'] else ""
        title = t['title']
        if len(title) > 28:
            title = title[:25] + "..."
        suffix = ""
        if t['deadline']:
            suffix = f" ⏰{days_left_str(t['deadline'], user_id)}"
        if t.get('repeat_days'):
            suffix += f" 🔁"
        label = f"{'✅ ' if t['is_done'] else ''}{prefix}{title}{suffix}"
        if not t['is_done']:
            buttons.append([
                InlineKeyboardButton(text=label, callback_data=f"task_done_{t['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"task_del_{t['id']}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text=label, callback_data="task_noop"),
                InlineKeyboardButton(text="🗑", callback_data=f"task_del_{t['id']}")
            ])
    buttons.append([InlineKeyboardButton(text="➕ Новая задача", callback_data="task_new")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))



def tasks_confirm_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="✅ Да, выполнена", callback_data=f"task_confirm_{task_id}"),
         InlineKeyboardButton(text="❌ Нет", callback_data="back_to_main")]
    ]))



def task_repeat_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="1️⃣ Разовая", callback_data="task_type_once")],
        [InlineKeyboardButton(text="🔁 Повторяющаяся", callback_data="task_type_repeat")]
    ]))



def task_days_keyboard(selected: list) -> InlineKeyboardMarkup:
    days = [(0,"Пн"),(1,"Вт"),(2,"Ср"),(3,"Чт"),(4,"Пт"),(5,"Сб"),(6,"Вс")]
    row = []
    buttons = []
    for num, name in days:
        mark = "✅" if str(num) in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"task_day_{num}"))
    buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✔️ Готово", callback_data="task_days_done")])
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb(buttons))



def task_priority_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🔥 Да, важная", callback_data="task_priority_yes"),
         InlineKeyboardButton(text="Нет", callback_data="task_priority_no")]
    ]))



def task_deadline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="📅 Добавить дедлайн", callback_data="task_deadline_yes"),
         InlineKeyboardButton(text="Пропустить", callback_data="task_deadline_no")]
    ]))
