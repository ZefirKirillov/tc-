// trackcheck/handlers/stats.py — stats and rank screens.

import * as repo from '../repo.js'
import { onCallback } from '../router.js'
import { send, del, sendPhoto, kb } from '../tg.js'
import { one } from '../turso.js'
import {
  createShortProgressBar, fix1, getRankName, getRankEmoji, getRankMotivation, getSparksForNextRank,
} from '../util.js'
import { renderChart } from '../charts.js'
import { backKeyboard, statsKeyboard, rankBackKeyboard, notifySettingsKeyboard } from './keyboards.js'
import { deleteTempMessages } from './helpers.js'

export async function showStatsChoice(c) {
  const { s, chatId } = c
  s.clear()
  if (s.lastMenu) {
    await del(chatId, s.lastMenu)
    s.lastMenu = null
  }
  await deleteTempMessages(c, true)
  const msg = await send(chatId, '📊 Выбери тип статистики:', { reply_markup: statsKeyboard() })
  s.temps.stats_choice = msg.message_id
  s.navPush('stats')
}

async function showStats(c) {
  const period = c.data.split(':')[1]
  const { userId, chatId, s } = c
  const name = await repo.getUserName(userId, c.from.first_name)
  await del(chatId, s.temps.stats_choice)
  if (period === 'week' || period === 'month') {
    const ratings = await repo.getRatings(userId, period === 'week' ? 7 : 30)
    let text = `📊 Статистика за ${period === 'week' ? 'неделю' : 'месяц'} | ${name}\n\n`
    for (const r of ratings) text += `${r.category}: ${fix1(r.avg_rating)}/10 ${createShortProgressBar(Math.trunc(r.avg_rating))}\n`
    const msg = await c.reply(text, { reply_markup: rankBackKeyboard() })
    s.temps.stats_result = msg.message_id
  } else if (period === 'chart_week' || period === 'chart_month') {
    const days = period === 'chart_week' ? 7 : 30
    await c.answer('📈 Генерирую...')
    const daily = await repo.getDailyRatings(userId, days)
    if (!daily.length) {
      const msg = await c.reply('❌ Нет данных для графика', { reply_markup: rankBackKeyboard() })
      s.temps.stats_result = msg.message_id
      return
    }
    const temp = await c.reply('📈 Генерирую график...')
    try {
      const png = await renderChart('reflection', { user_id: userId, days })
      if (png) await sendPhoto(userId, png, { caption: `📈 Динамика за ${days === 7 ? 'неделю' : 'месяц'}` })
    } finally {
      await del(chatId, temp.message_id)
    }
  }
}

export async function isNotifyEnabled(userId) {
  try {
    const row = await one('SELECT notify_enabled FROM user_settings WHERE user_id = ?', [userId])
    return !row || row.notify_enabled === null || !!row.notify_enabled
  } catch {
    return true
  }
}

export async function showRank(c) {
  const { s, userId, chatId } = c
  s.clear()
  const rank = await repo.getOrCreateRankData(userId)
  const name = await repo.getUserName(userId)
  const rankId = rank.current_rank
  const total = rank.total_sparks
  const [needed, nextTotal] = getSparksForNextRank(rankId, total)
  if (s.lastMenu) {
    await del(chatId, s.lastMenu)
    s.lastMenu = null
  }
  const text = `${name}, твой прогресс:

${getRankEmoji(rankId)} <b>${getRankName(rankId)}</b>
✨ Искр: ${total}/${nextTotal}
📊 Осталось до следующего ранга: ${needed}

<i>${getRankMotivation(rankId)}</i>`
  await deleteTempMessages(c, true)
  const rows = [...notifySettingsKeyboard(await isNotifyEnabled(userId)).inline_keyboard, ...backKeyboard().inline_keyboard]
  const msg = await send(chatId, text, { parse_mode: 'HTML', reply_markup: kb(rows) })
  s.temps.rank = msg.message_id
  s.navPush('rank')
}

export function register() {
  onCallback({ data: 'menu_stats' }, async (c) => { await c.deleteMsg(); await showStatsChoice(c) })
  onCallback({ prefix: 'stats:' }, showStats)
  onCallback({ data: 'menu_rank' }, async (c) => { await c.deleteMsg(); await showRank(c) })
}
