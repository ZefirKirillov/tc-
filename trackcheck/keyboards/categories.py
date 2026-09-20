from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.keyboards.common import with_back_kb


def reflection_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="😴 Сон", callback_data="refl:сон"),
         InlineKeyboardButton(text="🎮 Зависание", callback_data="refl:зависание")],
        [InlineKeyboardButton(text="🎯 Настрой", callback_data="refl:настрой")]
    ]))



def rating_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text=str(i), callback_data=f"rate:{i}") for i in range(1, 6)],
        [InlineKeyboardButton(text=str(i), callback_data=f"rate:{i}") for i in range(6, 11)]
    ]))
    return keyboard



def low_rating_keyboard(category: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb([
        [InlineKeyboardButton(text="🤖 Разобрать с ИИ", callback_data=f"analyze_low:{category}")],
        [InlineKeyboardButton(text="🔙 Пропустить", callback_data="skip_analysis")]
    ]))
    return keyboard
