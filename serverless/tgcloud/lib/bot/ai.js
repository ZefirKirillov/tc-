// trackcheck/handlers/ai.py — Check (questions/advice) and every «🔄 Попробовать еще раз».

import * as repo from '../repo.js'
import { onCallback, onMessage } from '../router.js'
import { send, del, edit, typing, esc, api } from '../tg.js'
import { all } from '../turso.js'
import { userToday } from '../dates.js'
import { stripMarkdown, foodConfirmText, nutritionMacros } from '../util.js'
import * as ai from '../ai.js'
import { RatingState, AIPlanState, WorkoutSessionState, DietState, AIAdvisorState } from './states.js'
import {
  retryAiKeyboard, aiReplyKeyboard, photoAnalysisBackKeyboard, reflectionKeyboard, dietConfirmFoodKeyboard,
} from './keyboards.js'
import { wpPlanReviewKeyboard, wpPlanReviewKeyboardManual, wpEditKeyboard, wpSettingsKeyboard } from './workout_keyboards.js'
import { formatFullPlan } from '../workout_service.js'
import { deleteTempMessages } from './helpers.js'
import { sendMainMenu } from './dashboard.js'
import { showReflectionMenu } from './categories.js'

const tryEdit = async (chatId, msgId, text, opts) => { try { await edit(chatId, msgId, text, opts) } catch { /* noop */ } }

/** Edits `phrases` into msgId on every relay heartbeat (~2 s) while the AI works. */
function animator(chatId, msgId, phrases) {
  let i = 0
  return async () => {
    i++
    await tryEdit(chatId, msgId, phrases[i % phrases.length])
  }
}

async function retryAiAction(c) {
  const action = c.data.split(':').slice(1).join(':')
  const handlers = {
    mood: async () => { c.s.setState(RatingState.waiting_for_mood_text); await retryMoodRating(c) },
    ai_advice: () => retryAiAdvice(c),
    ai_question: () => retryAiQuestion(c),
    generate_plan: () => retryGeneratePlan(c),
    low_rating: () => retryLowRating(c),
    food_calories: () => retryFoodCalories(c),
    food_photo: () => retryFoodPhoto(c),
    photo_analysis: () => retryPhotoAnalysis(c),
    manual_plan: () => retryManualPlan(c),
    monthly_review: () => retryMonthlyReview(c),
  }
  if (handlers[action]) await handlers[action]()
}

async function retryMoodRating(c) {
  const { s, userId, chatId } = c
  const description = s.getData().retry_mood_description || ''
  const name = await repo.getUserName(userId, c.from.first_name)
  const result = await ai.geminiGenerateRating(ai.moodPrompt(name, description, await ai.getFullContextForAi(userId)), 1024, { userId })
  if (!result) {
    await tryEdit(chatId, c.msg.message_id, '❌ ИИ не ответил. Попробуй ещё раз.', { reply_markup: retryAiKeyboard('mood') })
    return
  }
  await repo.saveRating(userId, 'настрой', result.rating, await userToday(userId))
  await tryEdit(chatId, c.msg.message_id, `🎯 Настрой: ${result.rating}/10\n\n${result.comment || ''}`, { reply_markup: reflectionKeyboard() })
  s.clear()
  if (await repo.checkAllCategoriesCompleted(userId)) {
    await repo.addSpark(userId, 'categories')
    await repo.updateStreak(userId)
    await sendMainMenu(c)
  } else {
    await showReflectionMenu(c, c.from.first_name)
  }
}

const THINKING = ['Думаю.', 'Думаю..', 'Думаю...', 'Анализирую.', 'Анализирую..', 'Анализирую...']

/** _stream_ai_reply: write the answer into msgId as it is generated; → answer | null */
export async function streamAiReply(c, msgId, prompt, header) {
  let started = false, lastEdit = 0
  const tick = animator(c.chatId, msgId, THINKING)
  const r = await ai.generate(prompt, {
    maxTokens: 8192, stream: true, userId: c.userId,
    onTick: async () => { if (!started) await tick() },
    onDelta: async (raw) => {
      const text = stripMarkdown(raw)
      if (!text) return
      started = true
      if (Date.now() - lastEdit < 1000) return
      lastEdit = Date.now()
      await tryEdit(c.chatId, msgId, `${header}\n\n${esc(text.slice(0, 3900))} ▌`, { parse_mode: 'HTML' })
    },
  })
  if (!r.text || !r.text.trim()) return null
  return stripMarkdown(r.text)
}

/** _show_ai_answer: final look (with buttons); → id of the answer message */
export async function showAiAnswer(c, msgId, header, answer) {
  const text = `${header}\n\n${esc(answer)}`
  try {
    await edit(c.chatId, msgId, text, { parse_mode: 'HTML', reply_markup: aiReplyKeyboard() })
    return msgId
  } catch {
    await del(c.chatId, msgId)
    const m = await send(c.chatId, text, { parse_mode: 'HTML', reply_markup: aiReplyKeyboard() })
    return m.message_id
  }
}

async function retryAiAdvice(c) {
  const prompt = c.s.getData().retry_ai_prompt || ''
  const header = '💡 <b>Совет:</b>'
  const msgId = c.msg.message_id
  const answer = await streamAiReply(c, msgId, prompt, header)
  if (!answer) {
    await tryEdit(c.chatId, msgId, `${ai.friendlyAiError().startsWith('⏳') ? ai.friendlyAiError() : '❌ ИИ не ответил. Попробуй ещё раз.'}`,
      { reply_markup: retryAiKeyboard('ai_advice') })
    return
  }
  await showAiAnswer(c, msgId, header, answer)
  await repo.saveLastAiAnswer(c.userId, answer)
}

async function retryAiQuestion(c) {
  const { userId } = c
  const name = await repo.getUserName(userId, c.from.first_name)
  const ctx = await ai.getFullContextForAi(userId)
  const prompt = ai.checkQuestionPrompt(name, ctx, c.s.getData().retry_ai_question || '')
  const header = '<b>Check:</b>'
  const msgId = c.msg.message_id
  const answer = await streamAiReply(c, msgId, prompt, header)
  if (!answer) {
    await tryEdit(c.chatId, msgId, `${ai.friendlyAiError().startsWith('⏳') ? ai.friendlyAiError() : '❌ ИИ не ответил. Попробуй ещё раз.'}`,
      { reply_markup: retryAiKeyboard('ai_question') })
    return
  }
  await showAiAnswer(c, msgId, header, answer)
  await repo.saveLastAiAnswer(userId, answer)
}

const PLAN_PHRASES = ['Анализирую...', 'Ищу пишущую ручку...', 'Составляю программу...',
  'Подбираю упражнения...', 'Рассчитываю нагрузку...', 'Финальные штрихи...']

async function retryGeneratePlan(c) {
  const { s, chatId } = c
  const data = s.getData()
  const goal = data.wp_goal || 'Общая форма'
  const level = data.wp_level || 'Средний'
  const days = data.wp_days || 3
  const notes = data.wp_notes || ''
  s.setState(AIPlanState.reviewing_plan)
  const msgId = s.temps.workout_menu
  const plan = await ai.geminiGeneratePlan(goal, level, days, notes, { userId: c.userId, onTick: animator(chatId, msgId, PLAN_PHRASES) })
  if (!plan || plan.pending) {
    await tryEdit(chatId, c.msg.message_id,
      plan && plan.pending ? ai.friendlyAiError() : 'Не удалось сгенерировать план. Попробуй ещё раз.',
      { reply_markup: retryAiKeyboard('generate_plan') })
    return
  }
  s.updateData({ wp_plan: plan })
  await tryEdit(chatId, c.msg.message_id, formatFullPlan(plan, goal, level, days), { reply_markup: wpPlanReviewKeyboard() })
}

async function retryLowRating(c) {
  const data = c.s.getData()
  await typing(c.chatId)
  const analysis = await ai.analyzeLowRating(c.userId, data.retry_low_rating_category || '', data.retry_low_rating_value || 0)
  if (analysis.startsWith('❌') || analysis.startsWith('⏳')) {
    await tryEdit(c.chatId, c.msg.message_id, '❌ ИИ не ответил. Нажми кнопку чтобы попробовать ещё раз.',
      { reply_markup: retryAiKeyboard('low_rating') })
    return
  }
  await c.reply(analysis, { reply_markup: aiReplyKeyboard() })
  await repo.saveLastAiAnswer(c.userId, analysis)
}

async function retryFoodCalories(c) {
  const description = c.s.getData().retry_food_description || ''
  await typing(c.chatId)
  const nutrition = await ai.estimateFoodNutrition(description, { userId: c.userId })
  if (!nutrition) {
    await tryEdit(c.chatId, c.msg.message_id,
      `❌ Не удалось определить калории для «${description}». Нажми кнопку чтобы попробовать ещё раз.`,
      { reply_markup: retryAiKeyboard('food_calories') })
    return
  }
  const macros = nutritionMacros(nutrition)
  c.s.updateData({ food_description: description, food_calories: nutrition.calories, food_macros: macros })
  c.s.setState(DietState.food_confirm)
  await tryEdit(c.chatId, c.msg.message_id, foodConfirmText(description, nutrition.calories, macros),
    { reply_markup: dietConfirmFoodKeyboard() })
}

/** Photos are kept as Telegram file_ids (not bytes) and downloaded again on retry. */
export async function downloadPhoto(fileId) {
  try { return await api.getFileContent(fileId) } catch { return null }
}

async function retryPhotoAnalysis(c) {
  const fileId = c.s.getData().retry_photo_file_id
  const image = fileId ? await downloadPhoto(fileId) : null
  let analysis
  if (!image) analysis = '❌ Фото больше не доступно. Отправь его заново.'
  else {
    try { analysis = await ai.scorePhotoForBot(c.userId, image) } catch (e) { analysis = `❌ Ошибка: ${String(e.message).slice(0, 100)}` }
  }
  if (analysis.startsWith('❌') || analysis.startsWith('⏳')) {
    await tryEdit(c.chatId, c.msg.message_id, analysis + '\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.',
      { reply_markup: retryAiKeyboard('photo_analysis') })
    return
  }
  await tryEdit(c.chatId, c.msg.message_id, analysis, { reply_markup: photoAnalysisBackKeyboard() })
  c.s.temps.photo_analysis_result = c.msg.message_id
  c.s.clear()
}

async function retryFoodPhoto(c) {
  const data = c.s.getData()
  const image = data.retry_food_photo_file_id ? await downloadPhoto(data.retry_food_photo_file_id) : null
  if (!image) {
    await tryEdit(c.chatId, c.msg.message_id, '❌ Фото больше не доступно. Отправь его заново.')
    return
  }
  await typing(c.chatId)
  const text = await ai.analyzeFoodPhoto(image, ai.FOOD_PHOTO_PROMPT, { userId: c.userId })
  if (!text) {
    await tryEdit(c.chatId, c.msg.message_id, '❌ Ошибка анализа фото.\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.',
      { reply_markup: retryAiKeyboard('food_photo') })
    return
  }
  const [description, nutrition] = ai.parseFoodPhoto(text)
  if (!nutrition) {
    await tryEdit(c.chatId, c.msg.message_id,
      `🍽 Определено: ${description}\n❌ Не удалось оценить калории.\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.`,
      { reply_markup: retryAiKeyboard('food_photo') })
    return
  }
  const macros = nutritionMacros(nutrition)
  c.s.updateData({ food_description: description, food_calories: nutrition.calories, food_macros: macros })
  c.s.setState(DietState.food_confirm)
  await tryEdit(c.chatId, c.msg.message_id, foodConfirmText(description, nutrition.calories, macros, true),
    { reply_markup: dietConfirmFoodKeyboard() })
}

const MANUAL_PHRASES = ['Читаю план...', 'Разбираю структуру...', 'Определяю дни...', 'Считаю подходы...', 'Почти готово...']

async function retryManualPlan(c) {
  const { s, chatId } = c
  const raw = s.getData().retry_manual_plan_text || ''
  if (!raw) {
    await tryEdit(chatId, c.msg.message_id, '❌ Текст плана не сохранился. Введи его заново.', { reply_markup: wpEditKeyboard() })
    return
  }
  s.setState(AIPlanState.reviewing_plan)
  const msgId = c.msg.message_id
  s.temps.workout_menu = msgId
  const opts = { userId: c.userId, onTick: animator(chatId, msgId, MANUAL_PHRASES) }
  let plan = await ai.geminiParseManualPlan(raw, opts)
  if (!plan) plan = await ai.fallbackParsePlan(raw, { ...opts, waitMs: 12000 })
  if (!plan || plan.pending) {
    s.setState(AIPlanState.entering_manual_plan)
    await tryEdit(chatId, msgId, (plan && plan.pending ? ai.friendlyAiError() : '❌ Не смог разобрать план.')
      + '\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.', { reply_markup: retryAiKeyboard('manual_plan') })
    return
  }
  s.updateData({ wp_plan: plan, wp_mode: 'manual', wp_goal: '', wp_level: '', wp_days: 0 })
  const text = formatFullPlan(plan, '', '', 0)
  try {
    await edit(chatId, msgId, text, { reply_markup: wpPlanReviewKeyboardManual() })
  } catch {
    const m = await c.reply(text, { reply_markup: wpPlanReviewKeyboardManual() })
    s.temps.workout_menu = m.message_id
  }
}

export async function recentSessionsForReview(userId) {
  const rows = await all('SELECT date, plan_json, status FROM ai_workout_sessions WHERE user_id = ? ORDER BY date DESC LIMIT 20', [userId])
  return rows.map(r => ({ date: r.date, status: r.status }))
}

export function reviewChangesText(chg) {
  const lines = ['Предлагаю заменить упражнения:\n']
  chg.forEach((ch, i) => lines.push(`${i + 1}. ${ch.old_exercise} → ${ch.new_exercise}\n   ${ch.reason}`))
  lines.push('\nНапиши номера изменений которые принять (например: 1 3) или «нет» чтобы отклонить всё:')
  return lines.join('\n')
}

async function retryMonthlyReview(c) {
  const { s, userId, chatId } = c
  const planData = await repo.getAiPlan(userId)
  if (!planData) {
    await c.answer('Нет плана', true)
    return
  }
  await typing(chatId)
  await tryEdit(chatId, c.msg.message_id, 'Анализирую прогресс...')
  const changes = await ai.geminiMonthlyReview(planData.plan, await recentSessionsForReview(userId), { userId })
  if (!changes) {
    await tryEdit(chatId, c.msg.message_id, '❌ Не удалось проанализировать прогресс.\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.',
      { reply_markup: retryAiKeyboard('monthly_review') })
    return
  }
  if (changes.no_changes_needed || !changes.changes || !changes.changes.length) {
    await tryEdit(chatId, c.msg.message_id, 'Менять ничего не нужно — план хорошо сбалансирован.', { reply_markup: wpSettingsKeyboard() })
    return
  }
  s.setState(WorkoutSessionState.monthly_review)
  s.updateData({ review_changes: changes.changes })
  await tryEdit(chatId, c.msg.message_id, reviewChangesText(changes.changes))
  s.navPush('wp_review_decline_prompt')
}

async function handleAi(c) {
  const { s, chatId } = c
  await c.deleteMsg()
  s.clear()
  if (s.lastMenu) {
    await del(chatId, s.lastMenu)
    s.lastMenu = null
  }
  await deleteTempMessages(c, true)
  const msg = await c.reply('Check тут, чем помочь?', { reply_markup: aiReplyKeyboard() })
  s.temps.ai_advisor = msg.message_id
  s.navPush('ai')
  s.setState(AIAdvisorState.waiting_for_question)
}

async function wpEditRetry(c) {
  const data = c.s.getData()
  const planData = await repo.getAiPlan(c.userId)
  const plan = data.wp_plan || (planData || {}).plan
  c.s.setState(AIPlanState.editing_plan)
  c.s.updateData({ wp_plan: plan })
  await tryEdit(c.chatId, c.msg.message_id,
    'Что хочешь изменить в плане?\n\nНапиши например:\n«убери приседания, замени на жим ногами»',
    { reply_markup: wpEditKeyboard() })
}

async function failAiAnswer(c, msgId, action) {
  await tryEdit(c.chatId, msgId, '❌ ИИ не ответил.')
  const why = ai.friendlyAiError()
  await c.reply(why.startsWith('⏳') ? why : '❌ ИИ не ответил. Нажми кнопку чтобы попробовать ещё раз.',
    { reply_markup: retryAiKeyboard(action) })
  c.s.setState(AIAdvisorState.waiting_for_question)
}

async function handleAiAdvice(c) {
  const { s, userId, chatId } = c
  await del(chatId, s.temps.ai_advisor)
  await typing(chatId)
  const name = await repo.getUserName(userId, c.from.first_name)
  const prompt = ai.checkAdvicePrompt(name, await ai.getFullContextForAi(userId))
  s.updateData({ retry_ai_prompt: prompt, retry_action: 'ai_advice' })
  const tmp = await c.reply('Думаю...')
  s.temps.ai_advisor = tmp.message_id
  const header = '💡 <b>Совет:</b>'
  const answer = await streamAiReply(c, tmp.message_id, prompt, header)
  if (!answer) return failAiAnswer(c, tmp.message_id, 'ai_advice')
  s.temps.ai_response = await showAiAnswer(c, tmp.message_id, header, answer)
  await repo.saveLastAiAnswer(userId, answer)
  s.setState(AIAdvisorState.waiting_for_question)
}

async function processAiQuestion(c) {
  const question = (c.text || '').trim()
  if (question.length < 3) {
    await c.reply('❌ Вопрос слишком короткий. Опиши подробнее!', { reply_markup: aiReplyKeyboard() })
    return
  }
  const { s, userId, chatId } = c
  await del(chatId, s.temps.ai_advisor)
  await typing(chatId)
  const name = await repo.getUserName(userId, c.from.first_name)
  const ctx = await ai.getFullContextForAi(userId)
  s.updateData({ retry_ai_question: question, retry_action: 'ai_question' })
  const prompt = ai.checkQuestionPrompt(name, ctx, question)
  const tmp = await c.reply('Думаю...')
  s.temps.ai_advisor = tmp.message_id
  const header = '<b>Check:</b>'
  const answer = await streamAiReply(c, tmp.message_id, prompt, header)
  if (!answer) return failAiAnswer(c, tmp.message_id, 'ai_question')
  s.temps.ai_response = await showAiAnswer(c, tmp.message_id, header, answer)
  await repo.saveLastAiAnswer(userId, answer)
}

async function showLastAi(c) {
  const last = await repo.getLastAiAnswer(c.userId)
  if (last) await c.reply(`<b>Последний ответ ИИ:</b>\n\n${last}`, { parse_mode: 'HTML', reply_markup: aiReplyKeyboard() })
  else await c.answer('Нет сохранённого ответа', true)
}

export function register() {
  onCallback({ prefix: 'retry_ai:' }, retryAiAction)
  onCallback({ data: 'menu_ai' }, handleAi)
  onCallback({ data: 'wp_edit_retry' }, wpEditRetry)
  onCallback({ data: 'ai_advice' }, handleAiAdvice)
  onMessage({ state: AIAdvisorState.waiting_for_question }, processAiQuestion)
  onCallback({ data: 'show_last_ai' }, showLastAi)
}
