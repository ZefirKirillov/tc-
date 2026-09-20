from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.keyboards.common import with_back_kb, _back_button_row


def stats_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="📆 Неделя", callback_data="stats:week"),
         InlineKeyboardButton(text="🗓 Месяц", callback_data="stats:month")],
        [InlineKeyboardButton(text="📈 График неделя", callback_data="stats:chart_week"),
         InlineKeyboardButton(text="📈 График месяц", callback_data="stats:chart_month")]
    ]))
    return keyboard



def rank_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[_back_button_row()])
