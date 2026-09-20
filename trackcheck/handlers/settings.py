import asyncio
from datetime import datetime

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    get_all_active_tasks, get_urgent_tasks_for_menu, complete_task, delete_task,
    add_task,
)
from trackcheck.states.settings import TaskState
from trackcheck.utils.dates import user_today_date
from trackcheck.utils.formatting import format_repeat_days
from trackcheck.utils.bot_helpers import delete_message_safe, delete_temp_messages
from trackcheck.keyboards.common import back_reply_keyboard
from trackcheck.keyboards.dashboard import urgent_tasks_keyboard
from trackcheck.keyboards.tasks import (
    tasks_menu_keyboard, tasks_confirm_keyboard, task_repeat_keyboard,
    task_days_keyboard, task_priority_keyboard, task_deadline_keyboard,
)
from trackcheck.runtime import user_temp_messages, user_last_menu, nav_push
from trackcheck.handlers import router


async def show_tasks_menu(user_id: int, chat_id: int, bot: Bot):
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.get('tasks_menu'))
    tasks = get_all_active_tasks(user_id)
    if tasks:
        text = "📝 Твои задачи:"
    else:
        text = "📝 Задач пока нет. Добавь первую!"
    kb = tasks_menu_keyboard(tasks, user_id)
    msg = await bot.send_message(chat_id, text, reply_markup=kb)
    nav_push(user_id, "tasks")
    temps['tasks_menu'] = msg.message_id
    user_temp_messages[user_id] = temps



@router.callback_query(F.data == "menu_tasks")
async def handle_tasks(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await state.clear()
    user_id = callback.from_user.id
    old_menu = user_last_menu.get(user_id)
    if old_menu:
        await delete_message_safe(bot, callback.message.chat.id, old_menu)
        user_last_menu[user_id] = None
    await delete_temp_messages(bot, user_id, callback.message.chat.id, keep_ai=True)
    await show_tasks_menu(user_id, callback.message.chat.id, bot)
    await callback.answer()



@router.callback_query(F.data == "task_noop")
async def task_noop(callback: CallbackQuery):
    await callback.answer()



@router.callback_query(F.data.startswith("task_done_"))
async def task_done_press(callback: CallbackQuery, bot: Bot, state: FSMContext):
    task_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    # Проверяем откуда нажали: из меню задач или из главного меню
    cursor = db.execute('SELECT title, is_priority FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id))
    row = cursor.fetchone()
    if not row:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    title = row[0][:40]
    await callback.message.edit_reply_markup(reply_markup=tasks_confirm_keyboard(task_id))
    await callback.answer(f"Выполнена: «{title}»?")



@router.callback_query(F.data.startswith("task_confirm_"))
async def task_confirm(callback: CallbackQuery, bot: Bot, state: FSMContext):
    task_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    complete_task(task_id, user_id)
    await callback.answer("✅ Готово!")
    # Check if this was from tasks_menu or urgent tasks in main menu
    temps = user_temp_messages.get(user_id, {})
    is_tasks_menu = temps.get('tasks_menu') == callback.message.message_id
    is_urgent_tasks = temps.get('urgent_tasks') == callback.message.message_id
    
    if is_urgent_tasks:
        # Urgent tasks in main menu area - just delete the message, don't show tasks menu
        urgent = get_urgent_tasks_for_menu(user_id)
        if not urgent:
            # Last task done - delete the urgent message
            try:
                await callback.message.delete()
            except:
                pass
            temps.pop('urgent_tasks', None)
            user_temp_messages[user_id] = temps
        else:
            # More tasks remain - edit the message with updated keyboard
            kb = urgent_tasks_keyboard(urgent, user_id)
            try:
                await callback.message.edit_reply_markup(reply_markup=kb)
            except:
                pass
    elif is_tasks_menu:
        # In tasks menu - refresh it
        try:
            await callback.message.delete()
        except:
            pass
        temps.pop('tasks_menu', None)
        user_temp_messages[user_id] = temps
        await show_tasks_menu(user_id, callback.message.chat.id, bot)
    else:
        # Unknown source - just delete the confirmation button
        try:
            await callback.message.delete()
        except:
            pass



@router.callback_query(F.data.startswith("task_del_"))
async def task_delete(callback: CallbackQuery, bot: Bot, state: FSMContext):
    task_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    delete_task(task_id, user_id)
    await callback.answer("🗑 Удалено")
    await show_tasks_menu(user_id, callback.message.chat.id, bot)
    try:
        await callback.message.delete()
    except:
        pass



@router.callback_query(F.data == "task_new")
async def task_new_start(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    await state.set_state(TaskState.entering_title)
    msg = await callback.message.answer("📝 Введи название задачи:",
                                         reply_markup=back_reply_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['task_create'] = msg.message_id
    await callback.answer()



@router.message(TaskState.entering_title)
async def task_enter_title(message: Message, bot: Bot, state: FSMContext):
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("❌ Слишком короткое название, попробуй ещё раз:")
        return
    try:
        await message.delete()
    except:
        pass
    temps = user_temp_messages.get(message.from_user.id, {})
    await delete_message_safe(bot, message.chat.id, temps.get('task_create'))
    await state.update_data(task_title=title)
    await state.set_state(TaskState.choosing_repeat)
    msg = await message.answer(f"Задача \u00ab{title}\u00bb\n\nОна разовая или повторяющаяся?", reply_markup=task_repeat_keyboard())
    user_temp_messages.setdefault(message.from_user.id, {})['task_create'] = msg.message_id



@router.callback_query(TaskState.choosing_repeat, F.data.in_({"task_type_once", "task_type_repeat"}))
async def task_choose_type(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    if callback.data == "task_type_once":
        await state.update_data(repeat_days=None)
        await state.set_state(TaskState.choosing_priority)
        msg = await callback.message.answer("🔥 Это важная задача?", reply_markup=task_priority_keyboard())
    else:
        await state.update_data(selected_days=[])
        await state.set_state(TaskState.choosing_days)
        msg = await callback.message.answer(
            "🔁 Выбери дни недели (можно несколько):",
            reply_markup=task_days_keyboard([])
        )
    user_temp_messages.setdefault(callback.from_user.id, {})['task_create'] = msg.message_id
    await callback.answer()



@router.callback_query(TaskState.choosing_days, F.data.startswith("task_day_"))
async def task_toggle_day(callback: CallbackQuery, bot: Bot, state: FSMContext):
    day = callback.data.split("_")[2]
    data = await state.get_data()
    selected = data.get('selected_days', [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    await state.update_data(selected_days=selected)
    await callback.message.edit_reply_markup(reply_markup=task_days_keyboard(selected))
    await callback.answer()



@router.callback_query(TaskState.choosing_days, F.data == "task_days_done")
async def task_days_done(callback: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    selected = data.get('selected_days', [])
    if not selected:
        await callback.answer("Выбери хотя бы один день!", show_alert=True)
        return
    repeat_days = ",".join(sorted(selected, key=int))
    await state.update_data(repeat_days=repeat_days)
    await callback.message.delete()
    await state.set_state(TaskState.choosing_priority)
    msg = await callback.message.answer("🔥 Это важная задача?", reply_markup=task_priority_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['task_create'] = msg.message_id
    await callback.answer()



@router.callback_query(TaskState.choosing_priority, F.data.in_({"task_priority_yes", "task_priority_no"}))
async def task_choose_priority(callback: CallbackQuery, bot: Bot, state: FSMContext):
    is_priority = callback.data == "task_priority_yes"
    await state.update_data(is_priority=is_priority)
    await callback.message.delete()
    await state.set_state(TaskState.choosing_deadline)
    msg = await callback.message.answer("📅 Хочешь добавить дедлайн?", reply_markup=task_deadline_keyboard())
    user_temp_messages.setdefault(callback.from_user.id, {})['task_create'] = msg.message_id
    await callback.answer()



@router.callback_query(TaskState.choosing_deadline, F.data.in_({"task_deadline_yes", "task_deadline_no"}))
async def task_choose_deadline(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await callback.message.delete()
    if callback.data == "task_deadline_yes":
        await state.set_state(TaskState.entering_deadline)
        msg = await callback.message.answer("📅 Введи дату дедлайна в формате ДД.ММ.ГГГГ:",
                                             reply_markup=back_reply_keyboard())
        user_temp_messages.setdefault(callback.from_user.id, {})['task_create'] = msg.message_id
    else:
        await state.update_data(deadline=None)
        await _save_task(callback.message, callback.from_user.id, bot, state)
    await callback.answer()



@router.message(TaskState.entering_deadline)
async def task_enter_deadline(message: Message, bot: Bot, state: FSMContext):
    text = message.text.strip()
    try:
        dl = datetime.strptime(text, '%d.%m.%Y')
        if dl.date() < user_today_date(message.from_user.id):
            await message.answer("❌ Дата уже прошла. Введи будущую дату:")
            return
        deadline_str = dl.strftime('%Y-%m-%d')
    except ValueError:
        err = await message.answer("❌ Неверный формат. Используй ДД.ММ.ГГГГ (например, 25.12.2025):")
        await asyncio.sleep(3)
        await delete_message_safe(bot, message.chat.id, err.message_id)
        return
    try:
        await message.delete()
    except:
        pass
    await state.update_data(deadline=deadline_str)
    await _save_task(message, message.from_user.id, bot, state)



async def _save_task(message, user_id: int, bot: Bot, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    title = data.get('task_title', '')
    is_priority = data.get('is_priority', False)
    deadline = data.get('deadline')
    repeat_days = data.get('repeat_days')
    add_task(user_id, title, is_priority, deadline, repeat_days)
    chat_id = message.chat.id
    temps = user_temp_messages.get(user_id, {})
    await delete_message_safe(bot, chat_id, temps.get('task_create'))
    # Показываем подтверждение
    parts = []
    if is_priority:
        parts.append("🔥 важная")
    if repeat_days:
        parts.append(f"🔁 {format_repeat_days(repeat_days)}")
    if deadline:
        parts.append(f"⏰ до {datetime.strptime(deadline, '%Y-%m-%d').strftime('%d.%m.%Y')}")
    detail = " | ".join(parts)
    confirm_msg = await bot.send_message(chat_id, f"\u2705 Задача добавлена!\n\u00ab{title}\u00bb" + (f"\n{detail}" if detail else ""))
    await asyncio.sleep(2)
    await delete_message_safe(bot, chat_id, confirm_msg.message_id)
    await show_tasks_menu(user_id, chat_id, bot)
