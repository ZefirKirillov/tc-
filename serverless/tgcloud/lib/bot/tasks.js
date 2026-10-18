// trackcheck/handlers/settings.py — tasks.

import * as repo from '../repo.js'
import { onCallback, onMessage } from '../router.js'
import { send, del, editMarkup } from '../tg.js'
import { userToday, isDateStr, ddmmyyyy } from '../dates.js'
import { one } from '../turso.js'
import { formatRepeatDays, pslice } from '../util.js'
import { TaskState } from './states.js'
import {
  backKeyboard, urgentTasksKeyboard, tasksMenuKeyboard, tasksConfirmKeyboard, taskRepeatKeyboard,
  taskDaysKeyboard, taskPriorityKeyboard, taskDeadlineKeyboard,
} from './keyboards.js'
import { deleteTempMessages, sendTemp } from './helpers.js'

export async function showTasksMenu(c) {
  const { s, userId, chatId } = c
  await del(chatId, s.temps.tasks_menu)
  const tasks = await repo.getAllActiveTasks(userId)
  const text = tasks.length ? '📝 Твои задачи:' : '📝 Задач пока нет. Добавь первую!'
  const msg = await send(chatId, text, { reply_markup: tasksMenuKeyboard(tasks, await userToday(userId)) })
  s.navPush('tasks')
  s.temps.tasks_menu = msg.message_id
}

async function handleTasks(c) {
  await c.deleteMsg()
  c.s.clear()
  if (c.s.lastMenu) {
    await del(c.chatId, c.s.lastMenu)
    c.s.lastMenu = null
  }
  await deleteTempMessages(c, true)
  await showTasksMenu(c)
}

const idFrom = (data) => parseInt(data.split('_')[2], 10)

async function taskDonePress(c) {
  const taskId = idFrom(c.data)
  const row = await one('SELECT title, is_priority FROM tasks WHERE id = ? AND user_id = ?', [taskId, c.userId])
  if (!row) {
    await c.answer('Задача не найдена', true)
    return
  }
  await editMarkup(c.chatId, c.msg.message_id, tasksConfirmKeyboard(taskId))
  await c.answer(`Выполнена: «${pslice(row.title, 0, 40)}»?`)
}

async function taskConfirm(c) {
  const taskId = idFrom(c.data)
  const { s, userId } = c
  await repo.completeTask(taskId, userId)
  await c.answer('✅ Готово!')
  const temps = s.temps
  const mid = c.msg.message_id
  if (temps.urgent_tasks === mid) {
    const urgent = await repo.getUrgentTasksForMenu(userId)
    if (!urgent.length) {
      await c.deleteMsg()
      delete temps.urgent_tasks
    } else {
      try { await editMarkup(c.chatId, mid, urgentTasksKeyboard(urgent, await userToday(userId))) } catch { /* noop */ }
    }
  } else if (temps.tasks_menu === mid) {
    await c.deleteMsg()
    delete temps.tasks_menu
    await showTasksMenu(c)
  } else {
    await c.deleteMsg()
  }
}

async function taskDelete(c) {
  await repo.deleteTask(idFrom(c.data), c.userId)
  await c.answer('🗑 Удалено')
  await showTasksMenu(c)
  await c.deleteMsg()
}

async function taskNewStart(c) {
  await c.deleteMsg()
  c.s.setState(TaskState.entering_title)
  const msg = await c.reply('📝 Введи название задачи:', { reply_markup: backKeyboard() })
  c.s.temps.task_create = msg.message_id
}

async function taskEnterTitle(c) {
  const title = (c.text || '').trim()
  if (title.length < 2) {
    await c.reply('❌ Слишком короткое название, попробуй ещё раз:')
    return
  }
  await c.deleteMsg()
  await del(c.chatId, c.s.temps.task_create)
  c.s.updateData({ task_title: title })
  c.s.setState(TaskState.choosing_repeat)
  const msg = await c.reply(`Задача «${title}»\n\nОна разовая или повторяющаяся?`, { reply_markup: taskRepeatKeyboard() })
  c.s.temps.task_create = msg.message_id
}

async function taskChooseType(c) {
  await c.deleteMsg()
  let msg
  if (c.data === 'task_type_once') {
    c.s.updateData({ repeat_days: null })
    c.s.setState(TaskState.choosing_priority)
    msg = await c.reply('🔥 Это важная задача?', { reply_markup: taskPriorityKeyboard() })
  } else {
    c.s.updateData({ selected_days: [] })
    c.s.setState(TaskState.choosing_days)
    msg = await c.reply('🔁 Выбери дни недели (можно несколько):', { reply_markup: taskDaysKeyboard([]) })
  }
  c.s.temps.task_create = msg.message_id
}

async function taskToggleDay(c) {
  const day = c.data.split('_')[2]
  const selected = c.s.getData().selected_days || []
  const i = selected.indexOf(day)
  if (i >= 0) selected.splice(i, 1)
  else selected.push(day)
  c.s.updateData({ selected_days: selected })
  await editMarkup(c.chatId, c.msg.message_id, taskDaysKeyboard(selected))
}

async function taskDaysDone(c) {
  const selected = c.s.getData().selected_days || []
  if (!selected.length) {
    await c.answer('Выбери хотя бы один день!', true)
    return
  }
  c.s.updateData({ repeat_days: [...selected].sort((a, b) => Number(a) - Number(b)).join(',') })
  await c.deleteMsg()
  c.s.setState(TaskState.choosing_priority)
  const msg = await c.reply('🔥 Это важная задача?', { reply_markup: taskPriorityKeyboard() })
  c.s.temps.task_create = msg.message_id
}

async function taskChoosePriority(c) {
  c.s.updateData({ is_priority: c.data === 'task_priority_yes' })
  await c.deleteMsg()
  c.s.setState(TaskState.choosing_deadline)
  const msg = await c.reply('📅 Хочешь добавить дедлайн?', { reply_markup: taskDeadlineKeyboard() })
  c.s.temps.task_create = msg.message_id
}

async function taskChooseDeadline(c) {
  await c.deleteMsg()
  if (c.data === 'task_deadline_yes') {
    c.s.setState(TaskState.entering_deadline)
    const msg = await c.reply('📅 Введи дату дедлайна в формате ДД.ММ.ГГГГ:', { reply_markup: backKeyboard() })
    c.s.temps.task_create = msg.message_id
  } else {
    c.s.updateData({ deadline: null })
    await saveTask(c)
  }
}

/** datetime.strptime(text, '%d.%m.%Y') → 'YYYY-MM-DD' or null */
function parseDdMmYyyy(text) {
  const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text)
  if (!m) return null
  const d = `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`
  return isDateStr(d) ? d : null
}

async function taskEnterDeadline(c) {
  const deadline = parseDdMmYyyy((c.text || '').trim())
  if (!deadline) {
    await sendTemp(c, '❌ Неверный формат. Используй ДД.ММ.ГГГГ (например, 25.12.2025):')
    return
  }
  if (deadline < await userToday(c.userId)) {
    await c.reply('❌ Дата уже прошла. Введи будущую дату:')
    return
  }
  await c.deleteMsg()
  c.s.updateData({ deadline })
  await saveTask(c)
}

async function saveTask(c) {
  const data = c.s.getData()
  c.s.clear()
  const title = data.task_title || ''
  const isPriority = data.is_priority || false
  const { deadline, repeat_days: repeatDays } = data
  await repo.addTask(c.userId, title, isPriority, deadline, repeatDays)
  await del(c.chatId, c.s.temps.task_create)
  const parts = []
  if (isPriority) parts.push('🔥 важная')
  if (repeatDays) parts.push(`🔁 ${formatRepeatDays(repeatDays)}`)
  if (deadline) parts.push(`⏰ до ${ddmmyyyy(deadline)}`)
  const detail = parts.join(' | ')
  await sendTemp(c, `✅ Задача добавлена!\n«${title}»` + (detail ? `\n${detail}` : ''))
  await showTasksMenu(c)
}

export function register() {
  onCallback({ data: 'menu_tasks' }, handleTasks)
  onCallback({ data: 'task_noop' }, async () => {})
  onCallback({ prefix: 'task_done_' }, taskDonePress)
  onCallback({ prefix: 'task_confirm_' }, taskConfirm)
  onCallback({ prefix: 'task_del_' }, taskDelete)
  onCallback({ data: 'task_new' }, taskNewStart)
  onMessage({ state: TaskState.entering_title }, taskEnterTitle)
  onCallback({ state: TaskState.choosing_repeat, when: c => ['task_type_once', 'task_type_repeat'].includes(c.data) }, taskChooseType)
  onCallback({ state: TaskState.choosing_days, prefix: 'task_day_' }, taskToggleDay)
  onCallback({ state: TaskState.choosing_days, data: 'task_days_done' }, taskDaysDone)
  onCallback({ state: TaskState.choosing_priority, when: c => ['task_priority_yes', 'task_priority_no'].includes(c.data) }, taskChoosePriority)
  onCallback({ state: TaskState.choosing_deadline, when: c => ['task_deadline_yes', 'task_deadline_no'].includes(c.data) }, taskChooseDeadline)
  onMessage({ state: TaskState.entering_deadline }, taskEnterDeadline)
}
