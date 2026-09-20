from typing import Any, Dict

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from trackcheck.database.repositories import get_ai_plan, get_user_name, get_diet_profile
from trackcheck.states.settings import AIAdvisorState
from trackcheck.states.workout import AIPlanState
from trackcheck.services.workout_service import _format_full_plan
from trackcheck.keyboards.common import with_back_kb, back_reply_keyboard
from trackcheck.keyboards.ai import ai_reply_keyboard
from trackcheck.keyboards.workouts import (
    wp_mode_keyboard, wp_goal_keyboard, wp_level_keyboard, wp_days_keyboard,
    wp_plan_review_keyboard, wp_plan_review_keyboard_manual,
)
from trackcheck.runtime import (nav_push, user_history_page, user_food_history_page,
                                user_temp_messages)
from trackcheck.utils.bot_helpers import delete_message_safe
from trackcheck.handlers.dashboard import send_main_menu
from trackcheck.handlers.categories import show_reflection_menu
from trackcheck.handlers.workouts import (
    show_workout_main_menu, show_ai_workout_today, _show_workout_manage_menu,
    _do_workout_manage, show_workout_history_page, show_history_page,
)
from trackcheck.handlers.food import show_diet_menu, _diet_log_food_start, show_food_history_page
from trackcheck.handlers.settings import show_tasks_menu
from trackcheck.handlers.stats import _show_stats_choice, _show_rank

SCREEN_RENDER: Dict[str, Any] = {}


async def render_screen(bot: Bot, user_id: int, chat_id: int, state: FSMContext, screen: str):
    render = SCREEN_RENDER.get(screen) or SCREEN_RENDER.get("main")
    await render(bot, user_id, chat_id, state)

async def _screen_send(bot, user_id, chat_id, text, keyboard, temps_key):
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.get(temps_key))
    # Гарантируем кнопку «Назад» под любым экраном: если клавиатуры нет —
    # ставим только «Назад», если есть — дописываем строку с «Назад».
    if keyboard is None:
        keyboard = back_reply_keyboard()
    else:
        rows = getattr(keyboard, "inline_keyboard", None)
        if rows is not None:
            keyboard = InlineKeyboardMarkup(inline_keyboard=with_back_kb(rows))
    msg = await bot.send_message(chat_id, text, reply_markup=keyboard)
    temps[temps_key] = msg.message_id
    user_temp_messages[user_id] = temps

async def _screen_main(bot, user_id, chat_id, state):
    await send_main_menu(bot, user_id, chat_id)

async def _screen_reflection(bot, user_id, chat_id, state):
    await show_reflection_menu(user_id, chat_id, bot, state)

async def _screen_workout(bot, user_id, chat_id, state):
    await show_workout_main_menu(user_id, chat_id, bot)

async def _screen_workout_today(bot, user_id, chat_id, state):
    await show_ai_workout_today(user_id, chat_id, bot, state)

async def _screen_workout_manage(bot, user_id, chat_id, state):
    await _show_workout_manage_menu(user_id, chat_id, bot, state)

async def _screen_categories(bot, user_id, chat_id, state):
    await _do_workout_manage(user_id, chat_id, bot)

async def _screen_diet(bot, user_id, chat_id, state):
    if get_diet_profile(user_id):
        await show_diet_menu(user_id, chat_id, bot)
    else:
        await send_main_menu(bot, user_id, chat_id)

async def _screen_diet_meal(bot, user_id, chat_id, state):
    await _diet_log_food_start(user_id, chat_id, bot, state)

async def _screen_tasks(bot, user_id, chat_id, state):
    await show_tasks_menu(user_id, chat_id, bot)

async def _screen_stats(bot, user_id, chat_id, state):
    await _show_stats_choice(user_id, chat_id, bot, state)

async def _screen_rank(bot, user_id, chat_id, state):
    await _show_rank(user_id, chat_id, bot, state)

async def _screen_ai(bot, user_id, chat_id, state):
    await state.set_state(AIAdvisorState.waiting_for_question)
    await _screen_send(bot, user_id, chat_id, "🤖 CheckAI тут, чем помочь?", ai_reply_keyboard(), 'ai_advisor')
    nav_push(user_id, "ai")

async def _screen_history(bot, user_id, chat_id, state):
    user_history_page[user_id] = 0
    await show_history_page(user_id, chat_id, bot, state)

async def _screen_workout_history(bot, user_id, chat_id, state):
    await show_workout_history_page(user_id, chat_id, bot, 0)

async def _screen_food_history(bot, user_id, chat_id, state):
    user_food_history_page[user_id] = 0
    await show_food_history_page(user_id, chat_id, bot, state)

async def _screen_wp_mode(bot, user_id, chat_id, state):
    await state.set_state(AIPlanState.choosing_mode)
    name = get_user_name(user_id)
    await _screen_send(bot, user_id, chat_id,
                       f"{name}, давай настроим тренировки!\n\nСоздать план с ИИ или введёшь свой?",
                       wp_mode_keyboard(), 'workout_menu')
    nav_push(user_id, "wp_mode")

async def _screen_wp_goal(bot, user_id, chat_id, state):
    await state.set_state(AIPlanState.choosing_goal)
    await _screen_send(bot, user_id, chat_id,
                       "Создание плана тренировок\n\nШаг 1 из 3\nКакая твоя цель?",
                       wp_goal_keyboard(), 'workout_menu')
    nav_push(user_id, "wp_goal")

async def _screen_wp_level(bot, user_id, chat_id, state):
    await state.set_state(AIPlanState.choosing_level)
    await _screen_send(bot, user_id, chat_id,
                       "Создание плана тренировок\n\nШаг 2 из 3\nТвой уровень подготовки?",
                       wp_level_keyboard(), 'workout_menu')
    nav_push(user_id, "wp_level")

async def _screen_wp_days(bot, user_id, chat_id, state):
    await state.set_state(AIPlanState.choosing_days_count)
    await _screen_send(bot, user_id, chat_id,
                       "Создание плана тренировок\n\nШаг 3 из 3\nСколько тренировок в неделю готов делать?",
                       wp_days_keyboard(), 'workout_menu')
    nav_push(user_id, "wp_days")

async def _screen_wp_notes(bot, user_id, chat_id, state):
    await state.set_state(AIPlanState.entering_extra_notes)
    await _screen_send(bot, user_id, chat_id,
                       "Есть пожелания или особенности?\n\n"
                       "Например: «травма колена», «нет штанги», «только утром»\nИли нажми Пропустить:",
                       InlineKeyboardMarkup(inline_keyboard=with_back_kb([
                           [InlineKeyboardButton(text="Пропустить →", callback_data="wp_notes_skip")]
                       ])), 'workout_menu')
    nav_push(user_id, "wp_notes")

async def _screen_wp_review(bot, user_id, chat_id, state):
    data = await state.get_data()
    plan = data.get("wp_plan")
    if not plan:
        plan_data = get_ai_plan(user_id)
        plan = plan_data["plan"] if plan_data else None
    if not plan:
        await _screen_workout_today(bot, user_id, chat_id, state)
        return
    await state.set_state(AIPlanState.reviewing_plan)
    text = _format_full_plan(plan, data.get("wp_goal", ""), data.get("wp_level", ""), data.get("wp_days", 3))
    keyboard = (wp_plan_review_keyboard_manual() if data.get("wp_mode") == "manual"
                else wp_plan_review_keyboard())
    await _screen_send(bot, user_id, chat_id, text, keyboard, 'workout_menu')
    nav_push(user_id, "wp_review")

async def _screen_wp_edit(bot, user_id, chat_id, state):
    await state.set_state(AIPlanState.editing_plan)
    await _screen_send(bot, user_id, chat_id,
                       "Что изменить в плане?\n\nНапример:\n«убери приседания, замени на жим ногами»\n«добавь кардио в пятницу»",
                       None, 'workout_menu')
    nav_push(user_id, "wp_edit")

async def _screen_wp_manual(bot, user_id, chat_id, state):
    await state.set_state(AIPlanState.entering_manual_plan)
    await _screen_send(bot, user_id, chat_id,
                       "Отправь план одним сообщением в формате:\nДень недели:\nНазвание упражнения - СетыxПовторения(Вес)\n\n"
                       "Пример: Жим лёжа - 3x5(110кг)", None, 'workout_menu')
    nav_push(user_id, "wp_manual")

WEX_DAY_NAMES = {"monday": "Пн", "tuesday": "Вт", "wednesday": "Ср", "thursday": "Чт",
                 "friday": "Пт", "saturday": "Сб", "sunday": "Вс"}

WEX_DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def _wex_day_buttons(user_id):
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        return None
    plan = plan_data.get("plan", {})
    cycle = plan_data.get("cycle_weeks", 1)
    buttons, seen_days = [], set()
    for w in range(1, cycle + 1):
        week = plan.get(f"week_{w}", {})
        for day_key in WEX_DAY_ORDER:
            if day_key in week and day_key not in seen_days:
                seen_days.add(day_key)
                buttons.append([InlineKeyboardButton(text=WEX_DAY_NAMES[day_key],
                                                     callback_data=f"wex_day_{day_key}")])
    return buttons

async def _screen_wex_days(bot, user_id, chat_id, state):
    buttons = _wex_day_buttons(user_id)
    if buttons is None:
        await _screen_workout_today(bot, user_id, chat_id, state)
        return
    await state.set_state(AIPlanState.editing_plan)
    await state.update_data(wp_edit_mode="exercise")
    await _screen_send(bot, user_id, chat_id, "Выбери день тренировки:",
                       InlineKeyboardMarkup(inline_keyboard=buttons), 'workout_menu')
    nav_push(user_id, "wex_days")

async def _screen_wex_ex(bot, user_id, chat_id, state):
    data = await state.get_data()
    day_key = data.get("wp_edit_day")
    if not day_key:
        await _screen_wex_days(bot, user_id, chat_id, state)
        return
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        await _screen_wex_days(bot, user_id, chat_id, state)
        return
    exercises = _wex_day_exercises(plan_data, day_key)
    if not exercises:
        await _screen_wex_days(bot, user_id, chat_id, state)
        return
    buttons = [[InlineKeyboardButton(text=ex.get("exercise", ex.get("name", f"Упражнение {i+1}")),
                                     callback_data=f"wex_ex_{i}")] for i, ex in enumerate(exercises)]
    await _screen_send(bot, user_id, chat_id, "Выбери упражнение для замены:",
                       InlineKeyboardMarkup(inline_keyboard=buttons), 'workout_menu')
    nav_push(user_id, "wex_ex")

def _wex_day_exercises(plan_data, day_key):
    plan = plan_data.get("plan", {})
    cycle = plan_data.get("cycle_weeks", 1)
    for w in range(1, cycle + 1):
        exs = plan.get(f"week_{w}", {}).get(day_key, [])
        if exs:
            return exs
    return []

async def _screen_wex_replace(bot, user_id, chat_id, state):
    data = await state.get_data()
    ex_name = data.get("wp_edit_ex_name")
    if not ex_name:
        await _screen_wex_ex(bot, user_id, chat_id, state)
        return
    await _screen_send(bot, user_id, chat_id,
                       f"Чем заменить «{ex_name}»?\n\nНапиши название нового упражнения:",
                       None, 'workout_menu')
    nav_push(user_id, "wex_replace")


SCREEN_RENDER.update({
    "main": _screen_main,
    "reflection": _screen_reflection,
    "workout": _screen_workout,
    "workout_today": _screen_workout_today,
    "workout_manage": _screen_workout_manage,
    "categories": _screen_categories,
    "diet": _screen_diet,
    "diet_meal": _screen_diet_meal,
    "tasks": _screen_tasks,
    "stats": _screen_stats,
    "rank": _screen_rank,
    "ai": _screen_ai,
    "history": _screen_history,
    "workout_history": _screen_workout_history,
    "food_history": _screen_food_history,
    "wp_mode": _screen_wp_mode,
    "wp_goal": _screen_wp_goal,
    "wp_level": _screen_wp_level,
    "wp_days": _screen_wp_days,
    "wp_notes": _screen_wp_notes,
    "wp_review": _screen_wp_review,
    "wp_edit": _screen_wp_edit,
    "wp_manual": _screen_wp_manual,
    "wp_review_decline_prompt": _screen_workout_today,
    "wex_days": _screen_wex_days,
    "wex_ex": _screen_wex_ex,
    "wex_replace": _screen_wex_replace,
})
