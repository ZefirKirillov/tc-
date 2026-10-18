// trackcheck/handlers/categories.py — daily reflection (check-in).

import * as repo from '../repo.js'
import { onCallback, onMessage } from '../router.js'
import { del, send, typing } from '../tg.js'
import { userToday } from '../dates.js'
import { getRankName } from '../util.js'
import { geminiGenerateRating, getFullContextForAi, analyzeLowRating, moodPrompt } from '../ai.js'
import { RatingState } from './states.js'
import { backKeyboard, retryAiKeyboard, aiReplyKeyboard, reflectionKeyboard, ratingKeyboard, lowRatingKeyboard } from './keyboards.js'
import { deleteTempMessages } from './helpers.js'
import { sendMainMenu } from './dashboard.js'

export async function showReflectionMenu(c, fallbackName = null) {
  const { s, userId, chatId } = c
  s.clear()
  const name = await repo.getUserName(userId, fallbackName)
  if (s.lastMenu) {
    await del(chatId, s.lastMenu)
    s.lastMenu = null
  }
  const temps = s.temps
  await del(chatId, temps.reflection); delete temps.reflection
  await del(chatId, temps.tasks_menu); delete temps.tasks_menu
  if (await repo.checkAllCategoriesCompleted(userId)) temps.all_categories_filled = true
  else delete temps.all_categories_filled
  // «Еда» and «активность» are automatic — once the manual three are in, we're done.
  if (await repo.manualCategoriesCompleted(userId)) {
    await repo.updateStreak(userId)
    await send(chatId, `${name}, на сегодня с рефлексией всё! 🎉\nЕда и активность посчитаются сами, как только ты их залогируешь.`)
    await deleteTempMessages(c, true)
    await sendMainMenu(c)
    return
  }
  const msg = await send(chatId, `${name}, что оценим?`, { reply_markup: reflectionKeyboard() })
  s.navPush('reflection')
  s.temps.reflection = msg.message_id
}

async function handleReflection(c) {
  await c.deleteMsg()
  await showReflectionMenu(c, c.from.first_name)
}

async function handleCategory(c) {
  const category = c.data.split(':').slice(1).join(':')
  const temps = c.s.temps
  if (category === 'настрой') {
    await c.deleteMsg()
    await del(c.chatId, temps.reflection)
    c.s.setState(RatingState.waiting_for_mood_text)
    const msg = await c.reply('🎯 Опиши в паре предложений, как прошёл твой день и что ты сегодня чувствовал(а):',
      { reply_markup: backKeyboard() })
    temps.rating = msg.message_id
    return
  }
  if (category !== 'сон' && category !== 'зависание') return
  await c.deleteMsg()
  await del(c.chatId, temps.reflection)
  c.s.updateData({ category })
  c.s.setState(RatingState.waiting_for_rating)
  const msg = await c.reply(`📝 Оцени ${category.toUpperCase()} за сегодня:`, { reply_markup: ratingKeyboard() })
  temps.rating = msg.message_id
}

async function processMoodText(c) {
  const description = (c.text || '').trim()
  if (description.length < 3) {
    await c.reply('Напиши чуть подробнее, как прошёл день 🙂')
    return
  }
  const { userId, chatId, s } = c
  await c.deleteMsg()
  await del(chatId, s.temps.rating)
  await typing(chatId)
  const thinking = await c.reply('Думаю...')
  s.temps.rating = thinking.message_id

  const name = await repo.getUserName(userId, c.from.first_name)
  const prompt = moodPrompt(name, description, await getFullContextForAi(userId))
  s.updateData({ retry_mood_description: description, retry_action: 'mood' })
  const result = await geminiGenerateRating(prompt, 1024, { userId })
  if (!result) {
    await del(chatId, s.temps.rating)
    await c.reply('❌ ИИ не ответил.', { reply_markup: retryAiKeyboard('mood') })
    return
  }
  await repo.saveRating(userId, 'настрой', result.rating, await userToday(userId))
  const replyText = `🎯 Настрой: ${result.rating}/10\n\n${result.comment || ''}`
  s.clear()
  await del(chatId, s.temps.rating)
  if (await repo.checkAllCategoriesCompleted(userId)) {
    await repo.addSpark(userId, 'categories')
    await repo.updateStreak(userId)
    await c.reply(replyText)
    await deleteTempMessages(c, true)
    await sendMainMenu(c)
  } else {
    const msg = await c.reply(replyText, { reply_markup: reflectionKeyboard() })
    s.temps.rating = msg.message_id
    await showReflectionMenu(c, c.from.first_name)
  }
}

async function processRating(c) {
  const { s, userId, chatId } = c
  await del(chatId, s.temps.reflection)
  const category = s.getData().category
  const rating = parseInt(c.data.split(':')[1], 10)
  if (Number.isNaN(rating)) return
  if (!['сон', 'зависание', 'еда', 'активность', 'настрой'].includes(category)) return
  await repo.saveRating(userId, category, rating, await userToday(userId))
  s.clear()
  const temps = s.temps
  await del(chatId, temps.rating)
  const name = await repo.getUserName(userId, c.from.first_name)
  const allCompleted = await repo.checkAllCategoriesCompleted(userId)
  const allFilledFlag = temps.all_categories_filled || false

  if (rating <= 3) {
    const msg = await c.reply(`${name}, низкая оценка ${category} (${rating}/10). Разобрать с ИИ почему так?`,
      { reply_markup: lowRatingKeyboard(category) })
    temps.low_rating = msg.message_id
    if (allCompleted || allFilledFlag) temps.all_categories_filled = true
    await showReflectionMenu(c, c.from.first_name)
    return
  }
  if (allCompleted) {
    const [success, , rankUp, , newRank] = await repo.addSpark(userId, 'categories')
    await repo.updateStreak(userId)
    if (success) {
      const todayRatings = await repo.getTodayRatings(userId)
      const vals = Object.values(todayRatings)
      const allHigh = vals.length === 5 && vals.every(v => v >= 8)
      if (allHigh) {
        await repo.addSpark(userId, 'bonus_high')
        await c.answer('✨ Искра + бонус за отличный день!')
      } else if (rankUp) {
        await c.answer(`✨ Новый ранг: ${getRankName(newRank)}!`)
      } else {
        await c.answer('✨ Искра зачислена.')
      }
    }
    await c.deleteMsg()
    await deleteTempMessages(c, true)
    await sendMainMenu(c)
  } else {
    await c.deleteMsg()
    await showReflectionMenu(c, c.from.first_name)
  }
}

async function analyzeLowRatingHandler(c) {
  const { s, userId, chatId } = c
  const category = c.data.split(':')[1]
  const rating = (await repo.getTodayRatings(userId))[category] || 0
  const temps = s.temps
  await del(chatId, temps.low_rating)
  const allFilled = temps.all_categories_filled || false
  await typing(chatId)
  const thinking = await c.reply('Думаю...')
  const analysis = await analyzeLowRating(userId, category, rating)
  await del(chatId, thinking.message_id)
  if (analysis.startsWith('❌') || analysis.startsWith('⏳')) {
    s.updateData({ retry_low_rating_category: category, retry_low_rating_value: rating, retry_action: 'low_rating' })
    await c.reply('❌ ИИ не ответил.', { reply_markup: retryAiKeyboard('low_rating') })
    if (allFilled) temps.all_categories_filled = true
    return
  }
  const msg = await c.reply(analysis, { reply_markup: aiReplyKeyboard() })
  temps.ai_response = msg.message_id
  if (allFilled) temps.all_categories_filled = true
  await repo.saveLastAiAnswer(userId, analysis)
}

async function skipAnalysis(c) {
  const temps = c.s.temps
  await del(c.chatId, temps.low_rating)
  if (temps.all_categories_filled) {
    await deleteTempMessages(c, true)
    await sendMainMenu(c)
  } else {
    await showReflectionMenu(c, c.from.first_name)
  }
}

export function register() {
  onCallback({ data: 'menu_reflection' }, handleReflection)
  onCallback({ prefix: 'refl:' }, handleCategory)
  onMessage({ state: RatingState.waiting_for_mood_text }, processMoodText)
  onCallback({ prefix: 'rate:' }, processRating)
  onCallback({ prefix: 'analyze_low:' }, analyzeLowRatingHandler)
  onCallback({ data: 'skip_analysis' }, skipAnalysis)
}
