from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.keyboards.common import with_back_kb, _back_button_row


def photo_analysis_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="❌ Отмена", callback_data="photo_analysis_cancel")]
    ]))



def photo_analysis_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[_back_button_row()])



def ai_reply_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="💡 Дай мне совет", callback_data="ai_advice")]
    ]))
