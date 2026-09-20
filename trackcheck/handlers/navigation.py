from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from trackcheck.runtime import nav_pop
from trackcheck.config import BACK_BUTTON_TEXT
from trackcheck.handlers import router


@router.message(F.text == BACK_BUTTON_TEXT)
async def universal_back(message: Message, bot: Bot, state: FSMContext):
    """Универсальная навигационная reply-кнопка: возвращает на один экран назад."""
    try:
        await message.delete()
    except Exception:
        pass
    user_id = message.from_user.id
    screen = nav_pop(user_id)
    # Экраны-шаги мастеров хранят данные в FSM — их не сбрасываем; для
    # остальных экранов кнопка «Назад» заодно отменяет незавершённый ввод.
    if screen not in {"wp_mode", "wp_goal", "wp_level", "wp_days", "wp_notes", "wp_review",
                      "wp_edit", "wp_manual", "wex_days", "wex_ex", "wex_replace",
                      "diet_meal", "ai"}:
        await state.clear()
    from trackcheck.screens import render_screen
    await render_screen(bot, user_id, message.chat.id, state, screen)



@router.callback_query(F.data == "nav_back")
async def universal_back_inline(callback: CallbackQuery, bot: Bot, state: FSMContext):
    """Универсальная навигационная inline-кнопка: возвращает на один экран назад."""
    user_id = callback.from_user.id
    screen = nav_pop(user_id)
    if screen not in {"wp_mode", "wp_goal", "wp_level", "wp_days", "wp_notes", "wp_review",
                      "wp_edit", "wp_manual", "wex_days", "wex_ex", "wex_replace",
                      "diet_meal", "ai"}:
        await state.clear()
    from trackcheck.screens import render_screen
    await render_screen(bot, user_id, callback.message.chat.id, state, screen)
    await callback.answer()
