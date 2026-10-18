// trackcheck/handlers/dashboard.py

import * as repo from '../repo.js'
import { onCallback } from '../router.js'
import { send, del, editMarkup } from '../tg.js'
import { userToday } from '../dates.js'
import { createNewProgressBar, workoutsProgress, getRankName, getRankEmoji, getSparksForNextRank, pyInt } from '../util.js'
import { mainMenuKeyboard, urgentTasksKeyboard } from './keyboards.js'
import { deleteTempMessages } from './helpers.js'

const CATEGORY_ICONS = [['сон', '😴'], ['еда', '🍽'], ['активность', '💪'], ['зависание', '🎮'], ['настрой', '🎯']]

export async function formatMainMenu(userId) {
  const today = await repo.getTodayRatings(userId)
  const workout = await repo.getOrCreateWorkoutData(userId)
  const rank = await repo.getOrCreateRankData(userId)
  const streak = await repo.getStreak(userId)
  const profile = await repo.getDietProfile(userId)
  let caloriesLine
  if (profile) {
    const todayCal = await repo.getTodayCalories(userId)
    const goal = profile.daily_calories
    const percent = goal > 0 ? todayCal / goal * 100 : 0
    caloriesLine = `🍽 Калории: ${pyInt(todayCal)}/${pyInt(goal)} (${pyInt(percent)}%)`
  } else {
    caloriesLine = '🍽 Диета не настроена'
  }
  const rankId = rank.current_rank
  const lines = ['┌─ TrackCheck ', '│', `│ <i>${getRankEmoji(rankId)} ${getRankName(rankId)} ${getRankEmoji(rankId)}</i>`, '│']
  for (const [cat, emoji] of CATEGORY_ICONS) {
    const r = today[cat]
    lines.push(`│ ${emoji} ${createNewProgressBar(r ? r : 0)}`)
  }
  lines.push('│')
  const [, nextTotal] = getSparksForNextRank(rankId, rank.total_sparks)
  lines.push(`│ 🏋️ ${workoutsProgress(workout)} | ✨ ${rank.total_sparks}/${nextTotal} искр`)
  lines.push(`│ ${caloriesLine}`)
  lines.push(`│ 🔥 Стрик: ${streak} дней`)
  lines.push('└─────────────────────')
  return lines.join('\n')
}

export async function sendMainMenu(c) {
  const { s, userId, chatId } = c
  s.navPush('main')
  let text = null
  try {
    text = await formatMainMenu(userId)
  } catch (e) {
    console.error('[BOT] ОШИБКА format_main_menu', e)
  }
  try {
    if (s.lastMenu) await del(chatId, s.lastMenu)
    await deleteTempMessages(c, true)
    if (text === null) text = '┌─ TrackCheck\n│\n│ ⚠️ Не удалось загрузить данные.\n└─────────────────────'
    const msg = await send(chatId, text, { reply_markup: mainMenuKeyboard(), parse_mode: 'HTML' })
    s.lastMenu = msg.message_id
    let urgent = []
    try {
      urgent = await repo.getUrgentTasksForMenu(userId)
    } catch (e) {
      console.error('[BOT] ОШИБКА get_urgent_tasks_for_menu', e)
    }
    if (urgent.length) {
      const m = await send(chatId, '⚡ Срочные задачи:', { reply_markup: urgentTasksKeyboard(urgent, await userToday(userId)) })
      s.temps.urgent_tasks = m.message_id
    } else {
      delete s.temps.urgent_tasks
    }
  } catch (e) {
    console.error('[BOT] ОШИБКА в send_main_menu', e)
    try {
      const msg = await send(chatId, '┌─ TrackCheck\n│\n│ ⚠️ Данные временно недоступны, выбери раздел:\n└─────────────────────',
        { reply_markup: mainMenuKeyboard() })
      s.lastMenu = msg.message_id
    } catch (e2) {
      console.error('[BOT] Критическая ошибка', e2)
    }
  }
}

async function backToMain(c) {
  c.s.clear()
  await c.deleteMsg()
  await deleteTempMessages(c, true)
  for (const key of ['photo_analysis_result', 'photo_user', 'body_fat_measurements', 'body_fat_result']) {
    if (key in c.s.temps) {
      try { await editMarkup(c.chatId, c.s.temps[key], null) } catch { /* noop */ }
    }
  }
  await sendMainMenu(c)
}

export function register() {
  onCallback({ data: 'back_to_main' }, backToMain)
  onCallback({ data: 'back_to_main_from_ai' }, backToMain)
}
