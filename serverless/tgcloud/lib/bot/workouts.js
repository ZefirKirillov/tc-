// trackcheck/handlers/workouts.py

import * as repo from '../repo.js'
import { onCallback, onMessage } from '../router.js'
import { send, del, edit, editMarkup, typing, btn, kb, withBack, sendPhoto, api } from '../tg.js'
import { execute, one, all, isUniqueViolation } from '../turso.js'
import { WEEKDAY_KEY, WEEKDAY_RU, WEEKDAY_FROM_KEY } from '../config.js'
import { userNow, userToday, ddmm, ddmmyyyy } from '../dates.js'
import {
  createWorkoutProgressBar, parseRepsInput, getRankName, pyIntParse, pyFloatParse, pyVal, pslice, pyFloat, pyJson,
} from '../util.js'
import * as ai from '../ai.js'
import * as ws from '../workout_service.js'
import { exerciseName, pget, pshow, formatWeight } from '../workout_service.js'
import { syncActivityRatingForToday } from '../tracker.js'
import { renderChart } from '../charts.js'
import { WorkoutState, AIPlanState, WorkoutSessionState } from './states.js'
import { backKeyboard, retryAiKeyboard, photoAnalysisCancelKeyboard, photoAnalysisBackKeyboard } from './keyboards.js'
import * as K from './workout_keyboards.js'
import { deleteTempMessages, sendTemp } from './helpers.js'
import { sendMainMenu } from './dashboard.js'
import { downloadPhoto, recentSessionsForReview, reviewChangesText } from './ai.js'

const tryEdit = async (chatId, msgId, text, opts) => {
  try { await edit(chatId, msgId, text, opts); return true } catch { return false }
}

function animator(chatId, msgId, phrases) {
  let i = 0
  return async () => { i++; if (msgId) await tryEdit(chatId, msgId, phrases[i % phrases.length]) }
}

// ───────────────────────── body photo ─────────────────────────

async function handlePhotoAnalysisStart(c) {
  await c.deleteMsg()
  c.s.clear()
  await deleteTempMessages(c, true)
  const intro = await c.reply(
    '📸 Отправь фото себя в полный рост или по пояс — оценю тело из 10, скажу сильные и слабые места и что с ними делать.\n\nИли нажми «❌ Отмена».',
    { reply_markup: photoAnalysisCancelKeyboard() })
  c.s.temps.photo_intro = intro.message_id
  c.s.setState('waiting_for_photo')
}

async function analyzePhoto(c) {
  const { s, userId, chatId } = c
  await del(chatId, s.temps.photo_intro)
  delete s.temps.photo_intro
  s.temps.photo_user = c.msg.message_id
  const status = await c.reply('🔍 Анализирую телосложение...')
  const image = await downloadPhoto(c.photoFileId)
  if (!image) {
    await tryEdit(chatId, status.message_id, '❌ Не удалось загрузить фото.')
    s.clear()
    await showWorkoutMainMenu(c)
    return
  }
  s.updateData({ retry_photo_file_id: c.photoFileId, retry_action: 'photo_analysis' })
  let analysis
  try {
    analysis = await ai.scorePhotoForBot(userId, image)
  } catch (e) {
    console.error(e)
    analysis = `❌ Ошибка: ${String(e.message).slice(0, 100)}`
  }
  await del(chatId, status.message_id)
  if (analysis.startsWith('❌') || analysis.startsWith('⏳')) {
    const r = await c.reply(analysis + '\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.', { reply_markup: retryAiKeyboard('photo_analysis') })
    s.temps.photo_analysis_result = r.message_id
    // keep retry data: clear only the state
    s.setState(null)
    return
  }
  const r = await c.reply(analysis, { reply_markup: photoAnalysisBackKeyboard() })
  s.temps.photo_analysis_result = r.message_id
  s.clear()
}

async function photoAnalysisCancel(c) {
  await del(c.chatId, c.s.temps.photo_intro)
  c.s.clear()
  await showWorkoutMainMenu(c)
  await c.deleteMsg()
}

async function photoAnalysisBack(c) {
  await deleteTempMessages(c, true)
  for (const key of ['photo_analysis_result', 'photo_user', 'body_fat_measurements', 'body_fat_result']) {
    if (key in c.s.temps) { try { await editMarkup(c.chatId, c.s.temps[key], null) } catch { /* noop */ } }
  }
  c.s.clear()
  await sendMainMenu(c)
}

async function photoTimeout(c) {
  await c.reply('Я ждал фото. Отмена.')
  c.s.clear()
  await showWorkoutMainMenu(c)
}

// ───────────────────────── workout main menu ─────────────────────────

export async function showWorkoutMainMenu(c) {
  const { s, userId, chatId } = c
  await del(chatId, s.temps.workout_menu); delete s.temps.workout_menu
  await del(chatId, s.temps.tasks_menu); delete s.temps.tasks_menu
  const [doneWeek, planWeek] = await repo.getWeeklyWorkoutProgress(userId)
  const bar = createWorkoutProgressBar(doneWeek, planWeek || 1)
  const now = await userNow(userId)
  let todayStr = ''
  const session = await repo.getTodaySession(userId)
  if (session && session.status === 'done') {
    const logs = await repo.getSessionExerciseLogs(session.id)
    if (logs.length) {
      todayStr = '\nСегодня:\n' + logs.map(log => {
        const icon = log.status === 'done' ? '✅' : '⏭'
        const res = log.result
        if (res && typeof res === 'object') {
          const w = res.weight_done
          return `${icon} ${log.exercise_name} — ${pshow(res, 'sets_done', '?')}×${pshow(res, 'reps_done', '?')}` + (w ? ` @ ${w}кг` : '')
        }
        return `${icon} ${log.exercise_name}`
      }).join('\n')
    }
  }
  const text = `🏋️ Тренировки\n\n${WEEKDAY_RU[now.weekday]}, ${ddmmyyyy(now.date)}\n\nНеделя: ${bar}` + todayStr
  const msg = await send(chatId, text, { reply_markup: K.workoutMainKeyboard() })
  s.navPush('workout')
  s.temps.workout_menu = msg.message_id
}

async function handleWorkouts(c) {
  await c.deleteMsg()
  c.s.clear()
  if (c.s.lastMenu) {
    await del(c.chatId, c.s.lastMenu)
    c.s.lastMenu = null
  }
  await deleteTempMessages(c, true)
  await showWorkoutMainMenu(c)
}

async function processWorkoutGoal(c) {
  const goal = pyIntParse(c.text)
  if (Number.isNaN(goal) || goal < 1 || goal > 31) {
    await c.reply('❌ Введи число от 1 до 31!')
    return
  }
  await repo.setWorkoutGoal(c.userId, goal)
  c.s.clear()
  await c.deleteMsg()
  await del(c.chatId, c.s.temps.workout_setup)
  await sendMainMenu(c)
}

// ───────────────────────── manual logging (categories/exercises) ─────────────────────────

const categoriesOf = async (userId) =>
  (await all('SELECT id, name FROM exercise_categories WHERE user_id = ? ORDER BY name', [userId])).map(r => [r.id, r.name])

async function doWorkoutAdd(c) {
  const { s, chatId } = c
  await del(chatId, s.temps.workout_menu); delete s.temps.workout_menu
  await del(chatId, s.temps.tasks_menu); delete s.temps.tasks_menu
  s.setState(WorkoutState.choosing_category)
  const msg = await send(chatId, 'Выбери категорию упражнения:', { reply_markup: K.workoutCategoriesKeyboard(await categoriesOf(c.userId), 'add') })
  s.temps.workout_temp = msg.message_id
}

async function workoutAddMsg(c) {
  await c.deleteMsg()
  c.s.clear()
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) {
    const name = await repo.getUserName(c.userId, c.from.first_name)
    const msg = await c.reply(`${name}, план тренировок не настроен.\n\nСоздать план с ИИ или введёшь свой?`, { reply_markup: K.wpModeKeyboard() })
    c.s.temps.workout_menu = msg.message_id
    c.s.navPush('wp_mode')
  } else {
    await showAiWorkoutToday(c)
  }
}

async function workoutAddStart(c) {
  await c.deleteMsg()
  await doWorkoutAdd(c)
}

async function workoutBackToMain(c) {
  await c.deleteMsg()
  c.s.clear()
  await sendMainMenu(c)
}

async function workoutAddChooseCategory(c) {
  if (c.s.getData().workout_charts_mode) return workoutChartsChooseCategory(c)
  const catId = parseInt(c.data.split('_')[3], 10)
  await c.deleteMsg()
  const exercises = (await all('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', [c.userId, catId])).map(r => [r.id, r.name])
  c.s.updateData({ category_id: catId })
  c.s.setState(WorkoutState.choosing_exercise)
  const msg = await c.reply('Выбери упражнение:', { reply_markup: K.workoutExercisesKeyboard(exercises, catId, 'add') })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutAddChooseExercise(c) {
  if (c.s.getData().workout_charts_mode) return workoutChartsGenerate(c)
  const exId = parseInt(c.data.split('_')[3], 10)
  const { userId } = c
  await c.deleteMsg()
  const row = await one('SELECT name, category_id, target_sets, target_reps, target_weight, target_distance, target_duration, weight_increment FROM exercises WHERE id = ?', [exId])
  if (!row) {
    await c.reply('❌ Упражнение не найдено.')
    await workoutAddStart(c)
    return
  }
  const { name: exName, category_id: catId, target_sets: tSets, target_reps: tReps, target_weight: tWeight,
    target_distance: tDist, target_duration: tDur, weight_increment: inc } = row
  const typeRow = await one('SELECT ex_type FROM exercise_categories WHERE id = ?', [catId])
  const exType = typeRow ? typeRow.ex_type : 'strength'
  let targetInfo = '', lastInfo = ''
  if (exType === 'strength' && tSets && tReps) {
    targetInfo = `\n🎯 Текущая цель: ${tSets}х${tReps}`
    if (tWeight) targetInfo += ` с весом ${pyFloat(tWeight)} кг`
    if (inc) targetInfo += ` (шаг +${pyFloat(inc)} кг)`
  } else if (exType === 'cardio' && tDist && tDur) {
    targetInfo = `\n🎯 Текущая цель: ${pyFloat(tDist)} км за ${tDur} мин`
  }
  const last = await one(`
    SELECT sets, reps, weight, distance, duration, date FROM workout_log
    WHERE user_id = ? AND exercise_name = ? AND category_id = ? ORDER BY date DESC LIMIT 1
  `, [userId, exName, catId])
  if (last) {
    const d = ddmm(last.date)
    if (exType === 'strength' && last.sets !== null) {
      lastInfo = `\n📊 Прошлый раз: ${last.sets}х${pyVal(last.reps)}`
      if (last.weight) lastInfo += ` (${pyFloat(last.weight)} кг)`
      lastInfo += ` (${d})`
    } else if (exType === 'cardio' && last.distance !== null) {
      lastInfo = `\n📊 Прошлый раз: ${pyFloat(last.distance)} км / ${pyVal(last.duration)} мин (${d})`
    }
  }
  c.s.updateData({
    exercise_id: exId, exercise_name: exName, category_id: catId, ex_type: exType,
    target_sets: tSets, target_reps: tReps, target_weight: tWeight,
    target_distance: tDist, target_duration: tDur, weight_increment: inc,
  })
  const msg = await c.reply(`Упражнение: ${exName}` + targetInfo + lastInfo + '\n\nВыбери действие:', { reply_markup: K.workoutActionChoiceKeyboard(exId) })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutManualEnter(c) {
  const exType = c.s.getData().ex_type || 'strength'
  await c.deleteMsg()
  let msg
  if (exType === 'cardio') {
    c.s.setState(WorkoutState.entering_distance)
    msg = await c.reply("Введи дистанцию в км (или отправь '-', если не хочешь указывать):", { reply_markup: backKeyboard() })
  } else {
    c.s.setState(WorkoutState.entering_reps)
    msg = await c.reply('Введи повторения.\nПримеры: 10, 10,8,6 или 3x10', { reply_markup: backKeyboard() })
  }
  c.s.temps.workout_temp = msg.message_id
}

async function workoutEnterReps(c) {
  const input = (c.text || '').trim()
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  const exType = c.s.getData().ex_type || 'strength'
  let msg
  if (exType === 'strength') {
    try {
      const [sets, reps] = parseRepsInput(input)
      c.s.updateData({ sets, reps: reps.join(',') })
      c.s.setState(WorkoutState.entering_weight)
      msg = await c.reply("Введи вес в кг (или отправь '-', если не хочешь указывать):", { reply_markup: backKeyboard() })
    } catch {
      msg = await c.reply('❌ Неверный формат. Попробуй ещё раз (например, 10, 10,8,6 или 3x10):')
    }
  } else {
    const parts = input.split(/\s+/).filter(Boolean)
    if (parts.length === 2) {
      const distance = pyFloatParse(parts[0].replace(',', '.'))
      const duration = pyIntParse(parts[1])
      if (!Number.isNaN(distance) && !Number.isNaN(duration)) {
        c.s.updateData({ distance, duration })
        await saveWorkoutAndContinue(c)
        return
      }
    }
    c.s.updateData({ distance: null, duration: null })
    c.s.setState(WorkoutState.entering_distance)
    msg = await c.reply("Введи дистанцию в км (или отправь '-', если не хочешь указывать):", { reply_markup: backKeyboard() })
  }
  c.s.temps.workout_temp = msg.message_id
}

async function saveWorkoutAndContinue(c) {
  const { userId } = c
  const data = c.s.getData()
  const exName = data.exercise_name
  const exType = data.ex_type || 'strength'
  const today = await userToday(userId)
  let resultText
  if (exType === 'strength') {
    const { sets, reps, weight = null } = data
    await execute('INSERT INTO workout_log (user_id, date, category_id, exercise_name, sets, reps, weight) VALUES (?, ?, ?, ?, ?, ?, ?)',
      [userId, today, data.category_id ?? null, exName, sets, reps, weight])
    resultText = `Сохранено: ${exName} – ${sets}х${reps}` + (weight ? ` (${pyFloat(weight)} кг)` : '')
  } else {
    const { distance = null, duration = null } = data
    await execute('INSERT INTO workout_log (user_id, date, category_id, exercise_name, distance, duration) VALUES (?, ?, ?, ?, ?, ?)',
      [userId, today, data.category_id ?? null, exName, distance, duration])
    const parts = []
    if (distance) parts.push(`${pyFloat(distance)} км`)
    if (duration) parts.push(`${duration} мин`)
    resultText = `Сохранено: ${exName}` + (parts.length ? ' – ' + parts.join(' / ') : '')
  }
  const count = (await one('SELECT COUNT(*) AS n FROM workout_log WHERE user_id = ? AND date = ?', [userId, today])).n
  let sparkAwarded = false
  if (count === 1) {
    await repo.addWorkout(userId)
    const [success, , rankUp, , newRank] = await repo.addSpark(userId, 'workout')
    if (success) {
      sparkAwarded = true
      await repo.updateStreak(userId)
      if (rankUp) await sendTemp(c, `✨ Новый ранг: ${getRankName(newRank)}!`)
    }
  }
  if (sparkAwarded) resultText += '\n✨ Искра за тренировку зачислена!'
  let targetBtn = null
  if (data.target_sets && data.target_reps) {
    if (!(data.sets === data.target_sets && data.reps === data.target_reps)) {
      targetBtn = btn(`🎯 Цель: ${data.target_sets}х${data.target_reps}` + (data.target_weight ? ` +${pyFloat(data.target_weight)}кг` : ''), `w_show_goal_${data.exercise_id}`)
    }
  } else if (data.target_distance && data.target_duration) {
    if (!(data.distance === data.target_distance && data.duration === data.target_duration)) {
      targetBtn = btn(`🎯 Цель: ${pyFloat(data.target_distance)}км / ${data.target_duration}мин`, `w_show_goal_${data.exercise_id}`)
    }
  }
  const markup = K.workoutContinueKeyboard()
  if (targetBtn) markup.inline_keyboard.unshift([targetBtn])
  c.s.setState(WorkoutState.confirm_continue)
  await c.reply(resultText, { reply_markup: markup })
}

async function workoutEnterWeight(c) {
  const str = (c.text || '').trim()
  let weight = null
  if (str !== '-') {
    weight = pyFloatParse(str.replace(',', '.'))
    if (Number.isNaN(weight)) {
      await c.reply("❌ Введи число или '-'.")
      return
    }
  }
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  c.s.updateData({ weight })
  await saveWorkoutAndContinue(c)
}

async function workoutEnterDistance(c) {
  const str = (c.text || '').trim()
  let distance = null
  if (str !== '-') {
    distance = pyFloatParse(str.replace(',', '.'))
    if (Number.isNaN(distance)) {
      await c.reply("❌ Введи число или '-'.")
      return
    }
  }
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  c.s.updateData({ distance })
  c.s.setState(WorkoutState.entering_duration)
  const msg = await c.reply("Введи время в минутах (или отправь '-', если не хочешь указывать):", { reply_markup: backKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutEnterDuration(c) {
  const str = (c.text || '').trim()
  let duration = null
  if (str !== '-') {
    duration = pyIntParse(str)
    if (Number.isNaN(duration) || duration <= 0) {
      await c.reply("❌ Введи положительное число или '-'.")
      return
    }
  }
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  c.s.updateData({ duration })
  await saveWorkoutAndContinue(c)
}

async function workoutContinueYes(c) {
  await c.deleteMsg()
  c.s.updateData({ sets: null, reps: null, weight: null, distance: null, duration: null })
  c.s.setState(WorkoutState.choosing_category)
  const msg = await c.reply('Выбери категорию упражнения:', { reply_markup: K.workoutCategoriesKeyboard(await categoriesOf(c.userId), 'add') })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutAchieveGoal(c) {
  const exId = parseInt(c.data.split('_')[3], 10)
  const { userId } = c
  const row = await one(`
    SELECT e.name, e.category_id, e.target_sets, e.target_reps, e.target_weight, e.weight_increment,
           e.target_distance, e.target_duration, c.ex_type
    FROM exercises e LEFT JOIN exercise_categories c ON e.category_id = c.id
    WHERE e.id = ? AND e.user_id = ?
  `, [exId, userId])
  if (!row) {
    await c.answer('❌ Упражнение не найдено', true)
    return
  }
  const today = await userToday(userId)
  const countBefore = (await one('SELECT COUNT(*) AS n FROM workout_log WHERE user_id = ? AND date = ?', [userId, today])).n
  let resultText
  if (row.ex_type === 'strength') {
    await execute('INSERT INTO workout_log (user_id, date, category_id, exercise_name, sets, reps, weight) VALUES (?, ?, ?, ?, ?, ?, ?)',
      [userId, today, row.category_id, row.name, row.target_sets, row.target_reps, row.target_weight])
    resultText = `Сохранено: ${row.name} – ${pyVal(row.target_sets)}х${pyVal(row.target_reps)}` + (row.target_weight ? ` (${pyFloat(row.target_weight)} кг)` : '')
  } else {
    await execute('INSERT INTO workout_log (user_id, date, category_id, exercise_name, distance, duration) VALUES (?, ?, ?, ?, ?, ?)',
      [userId, today, row.category_id, row.name, row.target_distance, row.target_duration])
    const parts = []
    if (row.target_distance) parts.push(`${pyFloat(row.target_distance)} км`)
    if (row.target_duration) parts.push(`${row.target_duration} мин`)
    resultText = `Сохранено: ${row.name}` + (parts.length ? ' – ' + parts.join(' / ') : '')
  }
  if (countBefore === 0) {
    await repo.addWorkout(userId)
    const [success, , rankUp, , newRank] = await repo.addSpark(userId, 'workout')
    if (success && rankUp) resultText += `\n✨ Новый ранг: ${getRankName(newRank)}!`
    else if (success) resultText += '\n✨ Искра за тренировку зачислена!'
  }
  await c.deleteMsg()
  await c.reply(resultText, { reply_markup: K.workoutContinueKeyboard() })
  c.s.setState(WorkoutState.confirm_continue)
  c.s.updateData({ sets: null, reps: null, weight: null, distance: null, duration: null })
}

// ───────────────────────── AI plan: today screen ─────────────────────────

export async function showAiWorkoutToday(c) {
  try {
    await showAiWorkoutTodayInner(c)
  } catch (e) {
    console.error('[WORKOUT TODAY] Error', e)
    await del(c.chatId, c.s.temps.workout_menu)
    const msg = await send(c.chatId, 'Произошла ошибка при загрузке плана. Попробуй ещё раз.', { reply_markup: K.wsRestDayKeyboard() })
    c.s.temps.workout_menu = msg.message_id
  }
}

async function showAiWorkoutTodayInner(c) {
  const { s, userId, chatId } = c
  const planData = await repo.getAiPlan(userId)
  if (!planData) return
  s.navPush('workout_today')
  const temps = s.temps
  let session = await repo.getTodaySession(userId)
  if (!session) {
    if (!(await repo.getTodayPlan(planData, userId))) {
      await del(chatId, temps.workout_menu)
      const [nextDate, nextDay] = await repo.getNextTrainingDay(planData, userId)
      let text = 'Сегодня день отдыха.'
      if (nextDate && nextDay) text += `\nСледующая тренировка: ${nextDay}, ${nextDate}`
      text += '\n\nХочешь потренироваться — запиши, что сделал, или возьми день из плана.'
      const msg = await send(chatId, text, { reply_markup: K.wsRestDayActionsKeyboard() })
      temps.workout_menu = msg.message_id
      return
    }
    session = await repo.createTodaySession(userId, planData)
    if (!session) throw new Error('today session was not created')
  }
  if (session.status === 'done' || session.status === 'skipped') {
    await del(chatId, temps.workout_menu)
    let text = 'Сегодняшняя тренировка уже записана.'
    const [nextDate, nextDay] = await repo.getNextTrainingDay(planData, userId)
    if (nextDate) text += `\nСледующая: ${nextDay}, ${nextDate}`
    const msg = await send(chatId, text, { reply_markup: K.wsRestDayKeyboard() })
    temps.workout_menu = msg.message_id
    return
  }
  const now = await userNow(userId)
  const sessionKey = session.session_key
  const prevSessions = await repo.getPreviousSameSession(userId, sessionKey, now.date)
  let exercises = session.plan
  if (exercises && !Array.isArray(exercises) && typeof exercises === 'object') exercises = Object.values(exercises)
  const keyParts = sessionKey.split('_')
  const dayKey = keyParts.length > 2 ? keyParts.slice(2).join('_') : keyParts[keyParts.length - 1]
  const extra = dayKey !== WEEKDAY_KEY[now.weekday]
  const planName = extra
    ? `Тренировка — ${WEEKDAY_RU[WEEKDAY_FROM_KEY[dayKey]] ?? dayKey} (доп.)`
    : `Тренировка — ${WEEKDAY_RU[now.weekday]}`
  const lines = [planName, ddmmyyyy(now.date), '']
  exercises.forEach((ex, i) => {
    let line = `${i + 1}. ${pyVal(exerciseName(ex))}  ${pshow(ex, 'sets', '?')}×${pshow(ex, 'reps', '?')}`
    if (ex.weight) line += ` @ ${ex.weight}кг`
    lines.push(line)
  })
  if (prevSessions && prevSessions.length) {
    const last = prevSessions[0]
    const important = []
    for (const log of last.logs || []) {
      if (log.status === 'skipped') important.push(`⏭ ${log.exercise_name} — пропущено`)
      else if (log.result && log.result.note) important.push(`⚠️ ${log.exercise_name} — ${log.result.note}`)
    }
    if (important.length) {
      lines.push(`\nПрошлый раз (${ddmm(last.date)}):`)
      lines.push(...important)
    }
  }
  s.setState(WorkoutSessionState.viewing_plan)
  s.updateData({ session_id: session.id, exercise_index: 0, prev_sessions: slimSessions(prevSessions || []) })
  const msg = await send(chatId, lines.join('\n'), { reply_markup: K.wsTodayKeyboard(extra) })
  temps.workout_menu = msg.message_id
}

/** prev_sessions live in the session store: keep only what the session screens read. */
function slimSessions(list) {
  return list.map(s => ({
    id: s.id, date: s.date, session_key: s.session_key, status: s.status,
    logs: (s.logs || []).map(l => ({ exercise_name: l.exercise_name, status: l.status, result: l.result ?? null })),
  }))
}

/** _edit_workout_menu: edit the workout_menu message, or send a new one. */
async function editWorkoutMenu(c, text, markup) {
  const msgId = c.s.temps.workout_menu
  if (msgId && await tryEdit(c.chatId, msgId, text, markup ? { reply_markup: markup } : {})) return
  const m = await c.reply(text, markup ? { reply_markup: markup } : {})
  c.s.temps.workout_menu = m.message_id
}

async function backToToday(c) {
  c.s.clear()
  await c.deleteMsg()
  delete c.s.temps.workout_menu
  await showAiWorkoutToday(c)
}

function formatResult(res) {
  const parts = []
  if (res.sets_done || res.reps_done) parts.push(`${res.sets_done || '?'}×${res.reps_done || '?'}`)
  if (res.weight_done) parts.push(`@ ${formatWeight(res.weight_done)}кг`)
  if (res.note) parts.push(`(${res.note})`)
  return parts.join(' ')
}

/** _count_workout: count it, then sync the activity rating. → [rankUp, newRank] */
async function countWorkoutAndSync(userId) {
  const [, rankUp, newRank] = await ws.countWorkout(userId)
  try { await syncActivityRatingForToday(userId) } catch (e) { console.error('[ACTIVITY RATING]', e) }
  return [rankUp, newRank]
}

async function wsPickDay(c) {
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) return c.answer('План не найден', true)
  const days = await ws.planDayOptions(planData, c.userId)
  if (!days.length) return c.answer('В плане нет тренировочных дней', true)
  const lines = ['Какой день из плана сделать сегодня?', '', ...days.map(d => `${d.label}: ${d.exercises.map(pyVal).join(', ')}`)]
  await tryEdit(c.chatId, c.msg.message_id, lines.join('\n'),
    { reply_markup: K.wsPickDayKeyboard(days.map(d => [d.key, `${d.label} · ${d.exercises.length} упр.`])) })
}

async function wsPickDayChosen(c) {
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) return c.answer('План не найден', true)
  const [, error] = await ws.startPlanDay(c.userId, planData, c.data.slice('ws_day_'.length))
  if (error) return c.answer(error === 'bad_day' ? 'Этого дня нет в плане' : 'На сегодня тренировка уже есть', true)
  await backToToday(c)
}

async function wsExtraCancel(c) {
  const session = await repo.getTodaySession(c.userId)
  if (session && session.status === 'pending') await repo.deleteSession(c.userId, session.id)
  await backToToday(c)
}

async function wsFreeLogStart(c) {
  c.s.setState(WorkoutSessionState.free_logging)
  c.s.temps.workout_menu = c.msg.message_id
  await tryEdit(c.chatId, c.msg.message_id,
    'Напиши, что сделал. Например:\nЖим лёжа 3×10 60кг, подтягивания 3×8, бег 5 км за 30 мин',
    { reply_markup: K.wsFreeLogKeyboard() })
}

async function wsFreeLogInput(c) {
  const { userId } = c
  const raw = (c.text || '').trim()
  await c.deleteMsg()
  if (!raw) return
  await editWorkoutMenu(c, 'Записываю...', null)
  const items = await ai.geminiParseFreeWorkout(raw, { userId })
  if (!items.length) {
    await editWorkoutMenu(c, 'Не получилось разобрать. Опиши иначе — упражнение, подходы×повторения, вес:', K.wsFreeLogKeyboard())
    return
  }
  const [session, results] = await ws.saveFreeWorkout(userId, items, raw)
  c.s.clear()
  if (!session) {
    await editWorkoutMenu(c, 'На сегодня тренировка уже записана.', K.wsRestDayKeyboard())
    return
  }
  const lines = ['Тренировка записана\n', ...results.map(r => `✅ ${r.exercise_name} ${formatResult(r.result)}`.trimEnd())]
  const [rankUp, newRank] = await countWorkoutAndSync(userId)
  const planData = await repo.getAiPlan(userId)
  const [nextDate, nextDay] = planData ? await repo.getNextTrainingDay(planData, userId) : [null, null]
  if (nextDate) lines.push(`\nСледующая тренировка: ${nextDay}, ${nextDate}`)
  if (rankUp) lines.push(`\n✨ Новый ранг: ${getRankName(newRank)}!`)
  await editWorkoutMenu(c, lines.join('\n'), K.wsRestDayKeyboard())
}

// ───────────────────────── AI plan wizard ─────────────────────────

const STEP1 = 'Создание плана тренировок\n\nШаг 1 из 3\nКакая твоя цель?'
const STEP2 = 'Создание плана тренировок\n\nШаг 2 из 3\nТвой уровень подготовки?'
const STEP3 = 'Создание плана тренировок\n\nШаг 3 из 3\nСколько тренировок в неделю готов делать?'
export const MANUAL_PLAN_HELP = 'Отправь план одним сообщением в таком формате:\n\n'
  + 'День недели:\n'
  + 'Название упражнения - СетыxПовторения(Вес)\n\n'
  + 'Примеры строк:\n'
  + 'Жим лёжа - 3x5(110кг)\n'
  + 'Подтягивания - 3x10(+20кг)\n'
  + 'Становая тяга - МАХ(120кг)\n'
  + 'Отжимания - МАХ повторений(20кг)\n'
  + 'Присед - 2x(от 80кг к 60кг)\n'
  + 'Тренировка навыков - 40 минут\n\n'
  + 'Если в один день разные упражнения по неделям:\n'
  + 'Понедельник:\n'
  + 'Неделя 1 - Жим лёжа - МАХ(120кг)\n'
  + 'Неделя 2 - Жим лёжа - 3x5(110кг)\n'
  + 'Неделя 3 - Жим на наклонной - 3x11(90кг)\n'
  + 'Разгибания трицепса - 3x12(40кг)\n\n'
  + 'Упражнения без метки «Неделя N» дублируются во все недели.\n\n'
  + '⚠️ Чем точнее формат — тем лучше ИИ разберёт план.'

export const notesKeyboard = () => kb(withBack([[btn('Пропустить →', 'wp_notes_skip')]]))
export const NOTES_TEXT = 'Есть пожелания или особенности?\n\nНапример: «травма колена», «нет штанги», «только утром»\nИли нажми Пропустить:'

async function wpChooseAi(c) {
  c.s.setState(AIPlanState.choosing_goal)
  await tryEdit(c.chatId, c.msg.message_id, STEP1, { reply_markup: K.wpGoalKeyboard() })
  c.s.navPush('wp_goal')
}

async function wpChooseManual(c) {
  c.s.setState(AIPlanState.entering_manual_plan)
  await tryEdit(c.chatId, c.msg.message_id, MANUAL_PLAN_HELP, { reply_markup: backKeyboard() })
  c.s.navPush('wp_manual')
}

async function wpBackToMode(c) {
  c.s.setState(AIPlanState.choosing_mode)
  const name = await repo.getUserName(c.userId, c.from.first_name)
  await tryEdit(c.chatId, c.msg.message_id, `${name}, давай настроим тренировки!\n\nСоздать план с ИИ или введёшь свой?`, { reply_markup: K.wpModeKeyboard() })
  c.s.navPush('wp_mode')
}

async function wpChooseGoal(c) {
  const map = { wp_goal_mass: 'Набор массы', wp_goal_loss: 'Похудение', wp_goal_strength: 'Сила', wp_goal_fitness: 'Общая форма' }
  c.s.updateData({ wp_goal: map[c.data] || 'Общая форма' })
  c.s.setState(AIPlanState.choosing_level)
  await tryEdit(c.chatId, c.msg.message_id, STEP2, { reply_markup: K.wpLevelKeyboard() })
  c.s.navPush('wp_level')
}

async function wpBackToGoal(c) {
  c.s.setState(AIPlanState.choosing_goal)
  await tryEdit(c.chatId, c.msg.message_id, STEP1, { reply_markup: K.wpGoalKeyboard() })
  c.s.navPush('wp_goal')
}

async function wpChooseLevel(c) {
  const map = { wp_level_beginner: 'Новичок', wp_level_intermediate: 'Средний', wp_level_advanced: 'Продвинутый' }
  c.s.updateData({ wp_level: map[c.data] || 'Средний' })
  c.s.setState(AIPlanState.choosing_days_count)
  await tryEdit(c.chatId, c.msg.message_id, STEP3, { reply_markup: K.wpDaysKeyboard() })
  c.s.navPush('wp_days')
}

async function wpBackToLevel(c) {
  c.s.setState(AIPlanState.choosing_level)
  await tryEdit(c.chatId, c.msg.message_id, STEP2, { reply_markup: K.wpLevelKeyboard() })
  c.s.navPush('wp_level')
}

async function wpChooseDays(c) {
  c.s.updateData({ wp_days: parseInt(c.data.split('_')[2], 10) })
  c.s.setState(AIPlanState.entering_extra_notes)
  await tryEdit(c.chatId, c.msg.message_id, NOTES_TEXT, { reply_markup: notesKeyboard() })
  c.s.navPush('wp_notes')
}

async function wpNotesSkip(c) {
  c.s.updateData({ wp_notes: '' })
  await generateAndShowPlan(c)
}

async function wpNotesInput(c) {
  await c.deleteMsg()
  c.s.updateData({ wp_notes: (c.text || '').trim() })
  await generateAndShowPlan(c)
}

const PLAN_PHRASES = ['Анализирую...', 'Ищу пишущую ручку...', 'Составляю программу...',
  'Подбираю упражнения...', 'Рассчитываю нагрузку...', 'Финальные штрихи...']

async function generateAndShowPlan(c) {
  const { s, chatId } = c
  const data = s.getData()
  const goal = data.wp_goal || 'Общая форма'
  const level = data.wp_level || 'Средний'
  const days = data.wp_days || 3
  const notes = data.wp_notes || ''
  s.setState(AIPlanState.reviewing_plan)
  const msgId = s.temps.workout_menu
  await tryEdit(chatId, msgId, PLAN_PHRASES[0])
  const plan = await ai.geminiGeneratePlan(goal, level, days, notes, { userId: c.userId, onTick: animator(chatId, msgId, PLAN_PHRASES) })
  if (!plan || plan.pending) {
    await tryEdit(chatId, msgId, plan && plan.pending ? ai.friendlyAiError() : 'Не удалось сгенерировать план. Попробуй ещё раз.',
      { reply_markup: retryAiKeyboard('generate_plan') })
    return
  }
  s.updateData({ wp_plan: plan, retry_action: 'generate_plan' })
  const text = ws.formatFullPlan(plan, goal, level, days)
  if (!(await tryEdit(chatId, msgId, text, { reply_markup: K.wpPlanReviewKeyboard() }))) {
    const m = await send(chatId, text, { reply_markup: K.wpPlanReviewKeyboard() })
    s.temps.workout_menu = m.message_id
  }
  s.navPush('wp_review')
}

async function wpBackToDays(c) {
  c.s.setState(AIPlanState.choosing_days_count)
  await tryEdit(c.chatId, c.msg.message_id, 'Создание плана тренировок\n\nШаг 3 из 3\nСколько тренировок в неделю?', { reply_markup: K.wpDaysKeyboard() })
  c.s.navPush('wp_days')
}

async function wpPlanEditStart(c) {
  c.s.setState(AIPlanState.editing_plan)
  await tryEdit(c.chatId, c.msg.message_id,
    'Что хочешь изменить в плане?\n\nНапиши например:\n«убери приседания, замени на жим ногами»\n«добавь кардио в пятницу»',
    { reply_markup: backKeyboard() })
  c.s.navPush('wp_edit')
}

async function wpBackToReview(c) {
  const data = c.s.getData()
  if (!data.wp_plan) return c.answer('Нет плана', true)
  c.s.setState(AIPlanState.reviewing_plan)
  await tryEdit(c.chatId, c.msg.message_id, ws.formatFullPlan(data.wp_plan, data.wp_goal || '', data.wp_level || '', data.wp_days ?? 3),
    { reply_markup: K.wpPlanReviewKeyboard() })
  c.s.navPush('wp_review')
}

async function handleExerciseReplace(c) {
  const { s, userId } = c
  await c.deleteMsg()
  const data = s.getData()
  const exIdx = data.wp_edit_ex_idx ?? 0
  const dayKey = data.wp_edit_day ?? 'monday'
  const oldName = data.wp_edit_ex_name ?? '?'
  const newName = (c.text || '').trim()
  const planData = await repo.getAiPlan(userId)
  if (!planData) return
  const plan = planData.plan || {}
  const cycle = planData.cycle_weeks ?? 1
  for (let w = 1; w <= cycle; w++) {
    const wk = `week_${w}`
    if (plan[wk] && dayKey in plan[wk]) {
      const exs = plan[wk][dayKey]
      if (exIdx < exs.length) exs[exIdx].exercise = newName
    }
  }
  await repo.updatePlanJson(userId, plan)
  s.clear()
  const confirm = `Заменено: «${oldName}» → «${newName}»`
  const msgId = s.temps.workout_menu
  if (msgId && await tryEdit(c.chatId, msgId, confirm)) return
  const m = await c.reply(confirm)
  s.temps.workout_menu = m.message_id
  s.navPush('workout_manage')
}

async function wpPlanEditInput(c) {
  const data = c.s.getData()
  if (data.wp_edit_mode === 'exercise_replace') return handleExerciseReplace(c)
  const { s, chatId } = c
  await c.deleteMsg()
  const editMsgId = s.temps.workout_menu
  const dots = ['Обновляю план.', 'Обновляю план..', 'Обновляю план...']
  if (editMsgId) await tryEdit(chatId, editMsgId, dots[0])
  const newPlan = await ai.geminiEditPlan(data.wp_plan, (c.text || '').trim(), { userId: c.userId, onTick: animator(chatId, editMsgId, dots) })
  if (!newPlan || newPlan.pending) {
    await tryEdit(chatId, editMsgId,
      newPlan && newPlan.pending ? ai.friendlyAiError() : 'Не удалось применить изменения. Попробуй сформулировать иначе.',
      { reply_markup: kb(withBack([[btn('🔄 Попробовать снова', 'wp_edit_retry')]])) })
    s.navPush('wp_edit')
    return
  }
  s.updateData({ wp_plan: newPlan })
  s.setState(AIPlanState.reviewing_plan)
  await tryEdit(chatId, editMsgId, ws.formatFullPlan(newPlan, data.wp_goal || '', data.wp_level || '', data.wp_days ?? 3),
    { reply_markup: K.wpPlanReviewKeyboard() })
}

async function wpPlanAccept(c) {
  const { s, userId } = c
  const data = s.getData()
  const plan = data.wp_plan
  if (!plan) return c.answer('План не найден. Попробуй сгенерировать заново.', true)
  const mode = data.wp_mode ?? (data.wp_goal ? 'ai' : 'manual')
  const cycleWeeks = plan && typeof plan === 'object' && !Array.isArray(plan) ? (pget(plan, 'cycle_weeks', 1)) : 1
  await repo.deleteAllWorkoutData(userId)
  await repo.saveAiPlan(userId, mode, data.wp_goal ?? '', data.wp_level ?? '', data.wp_days ?? 3, plan, cycleWeeks)
  s.clear()
  s.d.nav = s.d.nav.filter(x => !x.startsWith('wp_'))
  await tryEdit(c.chatId, c.msg.message_id, '✅ План сохранён! Возвращайся когда будешь готов тренироваться.')
  // Python showed this for 2 s; here it is cleared on the next interaction.
  s.deleteLater(c.chatId, c.msg.message_id)
  await showAiWorkoutToday(c)
}

const MANUAL_PHRASES = ['Читаю план...', 'Разбираю структуру...', 'Определяю дни...', 'Считаю подходы...', 'Почти готово...']

async function wpManualInput(c) {
  const { s, chatId } = c
  const raw = (c.text || '').trim()
  await c.deleteMsg()
  s.updateData({ retry_manual_plan_text: raw, retry_action: 'manual_plan' })
  const msgId = s.temps.workout_menu
  if (msgId) await tryEdit(chatId, msgId, MANUAL_PHRASES[0])
  const opts = { userId: c.userId, onTick: animator(chatId, msgId, MANUAL_PHRASES) }
  let plan = await ai.geminiParseManualPlan(raw, opts)
  if (!plan) plan = await ai.fallbackParsePlan(raw, { ...opts, waitMs: 12000 })
  if (!plan || plan.pending) {
    if (msgId) await del(chatId, msgId)
    try {
      const err = await c.reply(
        (plan && plan.pending ? ai.friendlyAiError() : '❌ Не смог разобрать план. Можно скинуть тот же текст — я попробую снова.'),
        { reply_markup: kb(withBack([[btn('🔄 Попробовать снова', 'retry_ai:manual_plan')]])) })
      s.temps.workout_error = err.message_id
    } catch (e) { console.error('[MANUAL INPUT] error message', e) }
    return
  }
  s.updateData({ wp_plan: plan, wp_mode: 'manual', wp_goal: '', wp_level: '', wp_days: 0 })
  s.setState(AIPlanState.reviewing_plan)
  const text = ws.formatFullPlan(plan, '', '', 0)
  if (msgId && await tryEdit(chatId, msgId, text, { reply_markup: K.wpPlanReviewKeyboardManual() })) return
  const m = await c.reply(text, { reply_markup: K.wpPlanReviewKeyboardManual() })
  s.temps.workout_menu = m.message_id
}

async function workoutMainAi(c) {
  c.s.clear()
  await c.deleteMsg()
  await showAiWorkoutToday(c)
}

async function backToWorkoutMain(c) {
  c.s.clear()
  await c.deleteMsg()
  await showWorkoutMainMenu(c)
}

// ───────────────────────── workout session ─────────────────────────

export async function wsStartWorkout(c) {
  const session = await repo.getTodaySession(c.userId)
  if (!session) return c.answer('Сессия не найдена', true)
  let exercises = session.plan
  if (exercises && !Array.isArray(exercises) && typeof exercises === 'object') exercises = Object.values(exercises)
  c.s.updateData({ exercises, exercise_index: 0, session_id: session.id })
  c.s.setState(WorkoutSessionState.in_exercise)
  await showExercise(c, 0, exercises)
}

async function showExercise(c, index, exercises) {
  const ex = exercises[index]
  const name = exerciseName(ex)
  const prevSessions = c.s.getData().prev_sessions || []
  let prevResult = null
  if (prevSessions.length) {
    for (const log of prevSessions[0].logs || []) {
      if (log.exercise_name === name && log.result && Object.keys(log.result).length) { prevResult = log.result; break }
    }
  }
  const text = ws.formatExerciseCard(ex, index + 1, exercises.length, prevResult)
  c.s.setState(WorkoutSessionState.in_exercise)
  const markup = K.wsExerciseKeyboard(index === 0)
  const msgId = c.s.temps.workout_menu
  if (msgId && await tryEdit(c.chatId, msgId, text, { reply_markup: markup })) return
  const m = await c.reply(text, { reply_markup: markup })
  c.s.temps.workout_menu = m.message_id
}

function current(c) {
  const data = c.s.getData()
  const exercises = data.exercises || []
  const index = data.exercise_index || 0
  return { data, exercises, index, sessionId: data.session_id, ex: exercises[index] }
}

async function wsExerciseDone(c) {
  const { index, sessionId, ex } = current(c)
  if (!ex) return
  const result = { sets_done: pget(ex, 'sets', null), reps_done: pget(ex, 'reps', null), weight_done: pget(ex, 'weight', null), completed: true, note: null }
  await ws.logExercise(sessionId, c.userId, exerciseName(ex), ex, result)
  c.s.updateData({ exercise_index: index + 1 })
  await advance(c, ws.planRaiseTarget(ex))
}

async function wsExerciseSkip(c) {
  const { index, sessionId, ex } = current(c)
  if (!ex) return
  await execute(`INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, status)
    VALUES (?, ?, ?, ?, 'skipped')`, [sessionId, c.userId, pget(ex, 'exercise', pget(ex, 'name', null)), pyJson(ex)])
  c.s.updateData({ exercise_index: index + 1 })
  await nextExerciseOrFinish(c)
}

async function wsExercisePrev(c) {
  const { index, sessionId, exercises } = current(c)
  if (index <= 0) return c.answer('Это первое упражнение', true)
  await execute(`DELETE FROM ai_exercise_logs WHERE session_id = ? AND user_id = ?
    AND id = (SELECT MAX(id) FROM ai_exercise_logs WHERE session_id = ? AND user_id = ?)`, [sessionId, c.userId, sessionId, c.userId])
  c.s.updateData({ exercise_index: index - 1 })
  await showExercise(c, index - 1, exercises)
}

async function wsExerciseTextInput(c) {
  const raw = (c.text || '').trim()
  await c.deleteMsg()
  if (!raw) return
  const { index, sessionId, ex } = current(c)
  if (!ex) return
  await editWorkoutMenu(c, 'Записываю...', null)
  const result = await ai.geminiParseExerciseResult(ex, raw, { userId: c.userId })
  await ws.logExercise(sessionId, c.userId, exerciseName(ex), ex, result, raw)
  c.s.updateData({ exercise_index: index + 1 })
  await advance(c, ws.planRaiseTarget(ex, result))
}

async function wsExerciseReplace(c) {
  const { ex } = current(c)
  if (!ex) return
  const name = exerciseName(ex)
  const suggestions = (await ws.substitutionSuggestions(c.userId, name)).map(sub =>
    [sub.id, `${sub.name} ${formatResult({ sets_done: sub.sets, reps_done: sub.reps, weight_done: sub.weight })}`.trimEnd()])
  let text = `Замена: ${pyVal(name)}\n\nНапиши, что сделал вместо — например «Жим гантелей 3×10 24кг».`
  if (suggestions.length) text += '\nИли выбери, что делал в прошлые разы:'
  c.s.setState(WorkoutSessionState.replacing_exercise)
  await editWorkoutMenu(c, text, K.wsReplaceKeyboard(suggestions))
}

async function wsReplaceBack(c) {
  const { index, exercises } = current(c)
  await showExercise(c, index, exercises)
}

async function wsReplaceSuggestion(c) {
  const idStr = c.data.slice('ws_sub_'.length)
  const sub = /^\d+$/.test(idStr) ? await repo.getExerciseSubstitution(c.userId, parseInt(idStr, 10)) : null
  if (!sub) return c.answer('Замена не найдена', true)
  const { index, sessionId, ex } = current(c)
  const [, raise] = await ws.logSubstitutionRepeat(c.userId, sessionId, ex, sub)
  c.s.updateData({ exercise_index: index + 1 })
  await advance(c, raise)
}

async function wsReplaceTextInput(c) {
  const raw = (c.text || '').trim()
  await c.deleteMsg()
  if (!raw) return
  const { index, sessionId, ex } = current(c)
  await editWorkoutMenu(c, 'Записываю...', null)
  const items = await ai.geminiParseFreeWorkout(raw, { userId: c.userId })
  if (!items.length) {
    await editWorkoutMenu(c, 'Не получилось разобрать. Опиши иначе — упражнение, подходы×повторения, вес:', K.wsReplaceKeyboard([]))
    return
  }
  const [, raise] = await ws.logSubstitutionItems(c.userId, sessionId, ex, items, raw)
  c.s.updateData({ exercise_index: index + 1 })
  await advance(c, raise)
}

async function advance(c, raiseTarget = null) {
  if (!raiseTarget) return nextExerciseOrFinish(c)
  c.s.updateData({ pending_raise: raiseTarget, raise_custom: false })
  c.s.setState(WorkoutSessionState.raising_weight)
  await editWorkoutMenu(c, `Цель выполнена 💪\n${raiseTarget.name} — ${formatWeight(raiseTarget.weight)} кг\n\nПоднять вес в следующий раз?`,
    K.wsRaiseWeightKeyboard())
}

async function wsRaiseWeight(c) {
  const choice = c.data.slice('ws_raise_'.length)
  const target = c.s.getData().pending_raise
  if (choice === 'custom') {
    c.s.updateData({ raise_custom: true })
    await tryEdit(c.chatId, c.msg.message_id, 'На сколько кг поднять? Напиши число, например 3.75:')
    return
  }
  if (target && choice !== 'keep') {
    const newWeight = await ws.applyWeightRaise(c.userId, target, parseFloat(choice))
    await c.answer(`В следующий раз: ${formatWeight(newWeight)} кг`)
  }
  c.s.updateData({ pending_raise: null })
  await nextExerciseOrFinish(c)
}

async function wsRaiseWeightCustom(c) {
  const raw = (c.text || '').trim().replace(/^\++/, '').replace(/,/g, '.')
  await c.deleteMsg()
  const data = c.s.getData()
  const target = data.pending_raise
  if (!data.raise_custom || !target) return
  const inc = pyFloatParse(raw)
  if (Number.isNaN(inc) || !(inc > 0 && inc <= 100)) {
    await editWorkoutMenu(c, 'Нужно число больше нуля, например 3.75:', null)
    return
  }
  await ws.applyWeightRaise(c.userId, target, inc)
  c.s.updateData({ pending_raise: null, raise_custom: false })
  await nextExerciseOrFinish(c)
}

async function nextExerciseOrFinish(c) {
  const { index, exercises } = current(c)
  if (index < exercises.length) await showExercise(c, index, exercises)
  else await finishWorkout(c)
}

async function finishWorkout(c) {
  const { userId } = c
  const sessionId = c.s.getData().session_id
  await execute("UPDATE ai_workout_sessions SET status='done', completed_at=? WHERE id=?", [await userToday(userId), sessionId])
  const logs = await repo.getSessionExerciseLogs(sessionId)
  const [rankUp, newRank] = await countWorkoutAndSync(userId)
  const lines = ['Тренировка завершена\n']
  for (const log of logs) {
    const res = log.result || {}
    if (log.status === 'skipped') lines.push(`⏭ ${log.exercise_name} — пропущено`)
    else if (res.replaced) lines.push(`🔄 ${log.exercise_name} — вместо «${res.replaced}»`)
    else if (res.note) lines.push(`⚠️ ${log.exercise_name} — ${res.note}`)
  }
  const planData = await repo.getAiPlan(userId)
  const [nextDate, nextDay] = planData ? await repo.getNextTrainingDay(planData, userId) : [null, null]
  if (nextDate) lines.push(`\nСледующая тренировка: ${nextDay}, ${nextDate}`)
  if (rankUp) lines.push(`\n✨ Новый ранг: ${getRankName(newRank)}!`)
  c.s.clear()
  await editWorkoutMenu(c, lines.join('\n'), K.wsRestDayKeyboard())
}

async function wsSkipDayStart(c) {
  c.s.setState(WorkoutSessionState.skipping_day)
  const text = 'Почему пропускаешь тренировку? Напиши кратко (или просто отправь «-»):'
  if (c.s.temps.workout_menu && await tryEdit(c.chatId, c.msg.message_id, text, { reply_markup: K.wsSkipDayKeyboard() })) return
  const m = await c.reply(text, { reply_markup: K.wsSkipDayKeyboard() })
  c.s.temps.workout_menu = m.message_id
}

async function wsBackToToday(c) {
  c.s.clear()
  await c.deleteMsg()
  delete c.s.temps.workout_menu
  await showAiWorkoutToday(c)
}

async function wsSkipDayReason(c) {
  const { s, userId, chatId } = c
  const raw = (c.text || '').trim()
  if (!raw) {
    await c.deleteMsg()
    try { await send(chatId, 'Напиши причину текстом (или «-»):') } catch { /* noop */ }
    return
  }
  const reason = raw === '-' ? '' : raw.slice(0, 500)
  await c.deleteMsg()
  try {
    let planData = await repo.getAiPlan(userId)
    if (planData) {
      const session = await repo.createTodaySession(userId, planData)
      if (session) await execute("UPDATE ai_workout_sessions SET status='skipped', skip_reason=? WHERE id=?", [reason, session.id])
    }
    await repo.deductSparkForSkip(userId)
    await syncActivityRatingForToday(userId)
    s.clear()
    let text = 'День пропущен.'
    planData = await repo.getAiPlan(userId)
    const [nextDate, nextDay] = planData ? await repo.getNextTrainingDay(planData, userId) : [null, null]
    if (nextDate) text += `\nСледующая тренировка: ${nextDay}, ${nextDate}`
    const msgId = s.temps.workout_menu
    if (msgId && await tryEdit(chatId, msgId, text, { reply_markup: K.wsRestDayKeyboard() })) return
    const m = await c.reply(text, { reply_markup: K.wsRestDayKeyboard() })
    s.temps.workout_menu = m.message_id
  } catch (e) {
    console.error(`[SKIP] ws_skip_day_reason failed user=${userId}`, e)
    s.clear()
    try { await send(chatId, 'Не удалось записать пропуск, попробуй ещё раз (кнопка «Пропустил день»).') } catch { /* noop */ }
  }
}

// ───────────────────────── plan settings & monthly review ─────────────────────────

async function wpSettings(c) {
  await tryEdit(c.chatId, c.msg.message_id, 'Настройки плана тренировок:', { reply_markup: K.wpSettingsKeyboard() })
}

async function wpReset(c) {
  await repo.deleteAllWorkoutData(c.userId)
  c.s.clear()
  const name = await repo.getUserName(c.userId, c.from.first_name)
  await tryEdit(c.chatId, c.msg.message_id, `${name}, давай настроим тренировки!\n\nСоздать план с ИИ или введёшь свой?`, { reply_markup: K.wpModeKeyboard() })
}

async function wpMonthlyReviewStart(c) {
  const { s, userId, chatId } = c
  await tryEdit(chatId, c.msg.message_id, 'Анализирую прогресс...')
  const planData = await repo.getAiPlan(userId)
  if (!planData) return c.answer('Нет плана', true)
  s.updateData({ retry_action: 'monthly_review' })
  const changes = await ai.geminiMonthlyReview(planData.plan, await recentSessionsForReview(userId), { userId })
  if (!changes) {
    await tryEdit(chatId, c.msg.message_id, '❌ Не удалось проанализировать прогресс.\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.',
      { reply_markup: retryAiKeyboard('monthly_review') })
    return
  }
  if (changes.no_changes_needed || !changes.changes || !changes.changes.length) {
    await tryEdit(chatId, c.msg.message_id, 'Менять ничего не нужно — план хорошо сбалансирован.', { reply_markup: K.wpSettingsKeyboard() })
    return
  }
  s.setState(WorkoutSessionState.monthly_review)
  s.updateData({ review_changes: changes.changes })
  await tryEdit(chatId, c.msg.message_id, reviewChangesText(changes.changes))
  s.navPush('wp_review_decline_prompt')
}

async function wpMonthlyReviewInput(c) {
  const { s, userId, chatId } = c
  await c.deleteMsg()
  const changes = s.getData().review_changes || []
  const text = (c.text || '').trim().toLowerCase()
  if (['нет', 'no', '-'].includes(text)) {
    s.clear()
    await send(chatId, 'Изменения отклонены. План остаётся прежним.', { reply_markup: K.wpSettingsKeyboard() })
    return
  }
  const indices = text.split(/\s+/).filter(x => /^\d+$/.test(x)).map(x => parseInt(x, 10) - 1)
  if (!indices.length) {
    await send(chatId, 'Не понял. Напиши номера через пробел или «нет».')
    return
  }
  const planData = await repo.getAiPlan(userId)
  if (planData) {
    await repo.updatePlanJson(userId, ws.applyMonthlyChanges(planData, indices, changes))
    await execute('UPDATE ai_workout_plan SET last_monthly_review=? WHERE user_id=?', [await userToday(userId), userId])
  }
  s.clear()
  const accepted = indices.filter(i => i >= 0 && i < changes.length).map(i => `${changes[i].old_exercise} → ${changes[i].new_exercise}`)
  await send(chatId, `Принято: ${accepted.join(', ')}\nПлан обновлён.`, { reply_markup: K.wpSettingsKeyboard() })
}

async function wpReviewDecline(c) {
  c.s.clear()
  await tryEdit(c.chatId, c.msg.message_id, 'Изменения отклонены.', { reply_markup: K.wpSettingsKeyboard() })
}

// ───────────────────────── manage categories & exercises ─────────────────────────

export async function doWorkoutManage(c) {
  const { s, chatId } = c
  await del(chatId, s.temps.workout_menu)
  delete s.temps.workout_menu
  const msg = await send(chatId, '📋 Мои категории:', { reply_markup: K.workoutCategoriesKeyboard(await categoriesOf(c.userId), 'manage') })
  s.navPush('categories')
  s.temps.workout_temp = msg.message_id
}

export async function showWorkoutManageMenu(c) {
  const { s, chatId } = c
  s.navPush('workout_manage')
  const planData = await repo.getAiPlan(c.userId)
  const mode = planData ? (pget(planData, 'mode', 'ai')) : 'ai'
  await del(chatId, s.temps.workout_menu)
  delete s.temps.workout_menu
  const msg = await send(chatId, 'Управление планом:', { reply_markup: K.workoutManageReplyKeyboard(mode) })
  s.temps.workout_menu = msg.message_id
}

async function workoutManageMsg(c) {
  const planData = await repo.getAiPlan(c.userId)
  await c.deleteMsg()
  if (!planData) {
    await c.reply('План не настроен. Зайди в «🏋️ Добавить выполнение» чтобы создать.', { reply_markup: K.workoutMainKeyboard() })
    c.s.navPush('workout')
    return
  }
  await showWorkoutManageMenu(c)
}

async function workoutEditPlanMsg(c) {
  await c.deleteMsg()
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) return
  c.s.setState(AIPlanState.editing_plan)
  c.s.updateData({ wp_plan: planData.plan, wp_goal: planData.goal ?? '', wp_level: planData.level ?? '', wp_days: planData.days_per_week ?? 3 })
  await del(c.chatId, c.s.temps.workout_menu)
  delete c.s.temps.workout_menu
  const msg = await c.reply('Что изменить в плане?\n\nНапример:\n«убери приседания, замени на жим ногами»\n«добавь кардио в пятницу»',
    { reply_markup: backKeyboard() })
  c.s.temps.workout_menu = msg.message_id
  c.s.navPush('wp_edit')
}

async function workoutNewAiPlanMsg(c) {
  await c.deleteMsg()
  const name = await repo.getUserName(c.userId, c.from.first_name)
  await del(c.chatId, c.s.temps.workout_menu)
  delete c.s.temps.workout_menu
  c.s.setState(AIPlanState.choosing_goal)
  const msg = await c.reply(`${name}, создаём новый план с нуля.\n\nШаг 1 из 3\nКакая твоя цель?`, { reply_markup: K.wpGoalKeyboard() })
  c.s.temps.workout_menu = msg.message_id
  c.s.navPush('wp_goal')
}

async function workoutManageBack(c) {
  c.s.clear()
  await c.deleteMsg()
  await showWorkoutMainMenu(c)
}

async function workoutManage(c) {
  await c.deleteMsg()
  await doWorkoutManage(c)
}

async function workoutMainCallback(c) {
  c.s.clear()
  await c.deleteMsg()
  await showWorkoutMainMenu(c)
}

async function workoutNewCategory(c) {
  await c.deleteMsg()
  c.s.setState(WorkoutState.creating_category)
  const msg = await c.reply("Введи название новой категории (например, 'Грудь', 'Кардио'):", { reply_markup: backKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutCreateCategory(c) {
  const name = (c.text || '').trim()
  if (name.length < 2) return c.reply('❌ Слишком короткое название. Попробуй ещё раз:')
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  c.s.updateData({ new_cat_name: name })
  const msg = await c.reply(`Тип категории «${name}»:`, { reply_markup: kb(withBack([
    [btn('💪 Силовая', 'cat_type_strength')],
    [btn('🚴 Кардио', 'cat_type_cardio')],
  ])) })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutCreateCategoryType(c) {
  const exType = c.data === 'cat_type_strength' ? 'strength' : 'cardio'
  const name = (c.s.getData().new_cat_name || '').trim()
  c.s.clear()
  await c.deleteMsg()
  if (name) {
    try {
      await execute('INSERT INTO exercise_categories (user_id, name, ex_type) VALUES (?, ?, ?)', [c.userId, name, exType])
    } catch (e) {
      if (!isUniqueViolation(e)) throw e
      await c.answer('❌ Такая категория уже существует.', true)
    }
  }
  await workoutManageAfterAction(c)
}

async function workoutManageAfterAction(c) {
  const { s, chatId } = c
  const old = s.temps.workout_temp
  delete s.temps.workout_temp
  if (old) await del(chatId, old)
  const msg = await send(chatId, '📋 Мои категории:', { reply_markup: K.workoutCategoriesKeyboard(await categoriesOf(c.userId), 'manage') })
  s.navPush('categories')
  s.temps.workout_temp = msg.message_id
}

async function workoutManageViewCategory(c) {
  const catId = parseInt(c.data.split('_')[3], 10)
  await c.deleteMsg()
  const row = await one('SELECT name FROM exercise_categories WHERE id = ?', [catId])
  if (!row) {
    await c.reply('❌ Категория не найдена.')
    await workoutManage(c)
    return
  }
  c.s.updateData({ current_cat_id: catId })
  const msg = await c.reply(`Категория: ${row.name}`, { reply_markup: K.workoutCategoryActionsKeyboard(catId) })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutRenameCategory(c) {
  c.s.updateData({ renaming_cat_id: parseInt(c.data.split('_')[3], 10) })
  await c.deleteMsg()
  c.s.setState(WorkoutState.renaming_category)
  const msg = await c.reply('Введи новое название для категории:', { reply_markup: backKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutRenameCategoryFinish(c) {
  const name = (c.text || '').trim()
  if (name.length < 2) return c.reply('❌ Слишком короткое название. Попробуй ещё раз:')
  const catId = c.s.getData().renaming_cat_id
  c.s.clear()
  await c.deleteMsg()
  if (catId) {
    try {
      await execute('UPDATE exercise_categories SET name = ? WHERE id = ? AND user_id = ?', [name, catId, c.userId])
    } catch (e) {
      if (!isUniqueViolation(e)) throw e
      await c.reply('❌ Категория с таким именем уже существует.')
    }
  }
  await workoutManageAfterAction(c)
}

async function workoutDeleteCategoryConfirm(c) {
  c.s.updateData({ deleting_cat_id: parseInt(c.data.split('_')[3], 10) })
  await c.deleteMsg()
  c.s.setState(WorkoutState.deleting_category_confirm)
  const msg = await c.reply('⚠️ Ты уверен, что хочешь удалить эту категорию? Все упражнения внутри тоже будут удалены.',
    { reply_markup: kb(withBack([[btn('✅ Да, удалить', 'w_cat_delete_yes'), btn('❌ Нет', 'workout_manage')]])) })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutDeleteCategoryFinish(c) {
  const catId = c.s.getData().deleting_cat_id
  if (!catId) {
    c.s.clear()
    await workoutManageAfterAction(c)
    return
  }
  // ON DELETE CASCADE in the schema is inert (foreign keys are off), as before.
  await execute('DELETE FROM exercise_categories WHERE id = ? AND user_id = ?', [catId, c.userId])
  c.s.clear()
  await c.deleteMsg()
  await sendTemp(c, '✅ Категория удалена.')
  await workoutManageAfterAction(c)
}

async function workoutManageExercises(c) {
  const catId = parseInt(c.data.split('_')[3], 10)
  await c.deleteMsg()
  const cat = await one('SELECT name FROM exercise_categories WHERE id = ?', [catId])
  if (!cat) {
    await c.reply('❌ Категория не найдена.')
    await workoutManage(c)
    return
  }
  const exercises = (await all('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', [c.userId, catId])).map(r => [r.id, r.name])
  c.s.updateData({ current_cat_id: catId })
  const msg = await c.reply(`Упражнения в категории '${cat.name}':`, { reply_markup: K.workoutExercisesKeyboard(exercises, catId, 'manage') })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutBackToCatsFromEx(c) {
  await c.deleteMsg()
  c.s.setState(WorkoutState.choosing_category)
  const msg = await c.reply('Выбери категорию упражнения:', { reply_markup: K.workoutCategoriesKeyboard(await categoriesOf(c.userId), 'add') })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutManageViewExercise(c) {
  const exId = parseInt(c.data.split('_')[3], 10)
  await c.deleteMsg()
  const row = await one('SELECT name, category_id FROM exercises WHERE id = ?', [exId])
  if (!row) {
    await c.reply('❌ Упражнение не найдено.')
    await workoutManage(c)
    return
  }
  c.s.updateData({ current_ex_id: exId, current_cat_id: row.category_id })
  const msg = await c.reply(`Упражнение: ${row.name}`, { reply_markup: K.workoutExerciseActionsKeyboard(exId) })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutSetGoalFromManage(c) {
  const exId = parseInt(c.data.split('_')[4], 10)
  await c.deleteMsg()
  const row = await one('SELECT category_id FROM exercises WHERE id = ? AND user_id = ?', [exId, c.userId])
  if (!row) return c.answer('❌ Упражнение не найдено', true)
  c.s.updateData({ creating_ex_id: exId, category_id: row.category_id })
  c.s.setState(WorkoutState.setting_goal_type)
  const msg = await c.reply('Выбери тип цели:', { reply_markup: K.workoutExerciseGoalKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutNewExercise(c) {
  c.s.updateData({ category_id: parseInt(c.data.split('_')[3], 10) })
  await c.deleteMsg()
  c.s.setState(WorkoutState.creating_exercise)
  const msg = await c.reply("Введи название нового упражнения (например, 'Жим лёжа', 'Бег'):", { reply_markup: backKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutCreateExercise(c) {
  const name = (c.text || '').trim()
  if (name.length < 2) return c.reply('❌ Слишком короткое название. Попробуй ещё раз:')
  const catId = c.s.getData().category_id
  if (!catId) {
    c.s.clear()
    await workoutManageAfterAction(c)
    return
  }
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  let newId
  try {
    newId = (await execute('INSERT INTO exercises (user_id, category_id, name) VALUES (?, ?, ?)', [c.userId, catId, name])).lastInsertRowid
  } catch (e) {
    if (!isUniqueViolation(e)) throw e
    await c.reply('❌ Такое упражнение уже есть в этой категории.')
    await workoutManageExercisesCat(c, catId)
    return
  }
  c.s.updateData({ creating_ex_id: newId })
  c.s.setState(WorkoutState.setting_goal_type)
  const msg = await c.reply('Хочешь установить цель для этого упражнения?\nВыбери тип:', { reply_markup: K.workoutExerciseGoalKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function setGoalStrength(c) {
  await c.deleteMsg()
  c.s.setState(WorkoutState.setting_strength_goal)
  const msg = await c.reply('Введи цель для силового упражнения в формате: подходы x повторения (например, 3x10)\n'
    + 'Если хочешь указать целевой вес и шаг увеличения, добавь ещё два числа через пробел: 3x10 50 2.5', { reply_markup: backKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function setStrengthGoalFinish(c) {
  const text = (c.text || '').trim()
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  const parts = text.split(/\s+/).filter(Boolean)
  if (!parts.length) return c.reply('❌ Введи цель (например, 3x10 или 10 8 6).')
  const nums = parts.slice(1).map(p => pyFloatParse(p.replace(',', '.'))).filter(n => Number.isFinite(n) && n >= 0)
  const targetWeight = nums.length > 0 ? nums[0] : null
  const weightIncrement = nums.length > 1 ? nums[1] : null
  let targetSets, targetReps
  try {
    const [sets, list] = parseRepsInput(parts[0])
    targetSets = sets
    targetReps = list.join(',')
  } catch {
    const msg = await c.reply('❌ Неверный формат цели. Используй примеры:\n- 3x10\n- 10 8 6\n- 3x10 50 2.5')
    c.s.temps.workout_temp = msg.message_id
    return
  }
  const data = c.s.getData()
  if (!data.creating_ex_id) {
    c.s.clear()
    await workoutManageAfterAction(c)
    return
  }
  await execute('UPDATE exercises SET target_sets = ?, target_reps = ?, target_weight = ?, weight_increment = ? WHERE id = ? AND user_id = ?',
    [targetSets, targetReps, targetWeight, weightIncrement, data.creating_ex_id, c.userId])
  c.s.clear()
  await sendTemp(c, '✅ Цель установлена!')
  await workoutManageExercisesCat(c, data.category_id)
}

async function setGoalCardio(c) {
  await c.deleteMsg()
  c.s.setState(WorkoutState.setting_cardio_goal)
  const msg = await c.reply('Введи цель для кардио в формате: дистанция км / время мин (например, 5 30)', { reply_markup: backKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function setCardioGoalFinish(c) {
  const text = (c.text || '').trim()
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.workout_temp)
  const parts = text.split(/\s+/).filter(Boolean)
  if (parts.length !== 2) {
    const msg = await c.reply('❌ Нужно два числа: дистанция (км) и время (мин).')
    c.s.temps.workout_temp = msg.message_id
    return
  }
  const dist = pyFloatParse(parts[0].replace(',', '.'))
  const dur = pyIntParse(parts[1])
  if (!Number.isFinite(dist) || !(dist > 0 && dist <= 1000) || Number.isNaN(dur) || !(dur > 0 && dur <= 24 * 60)) {
    const msg = await c.reply('❌ Неверный формат чисел.')
    c.s.temps.workout_temp = msg.message_id
    return
  }
  const data = c.s.getData()
  let ok
  if (data.creating_ex_id) {
    await execute('UPDATE exercises SET target_distance = ?, target_duration = ? WHERE id = ? AND user_id = ?', [dist, dur, data.creating_ex_id, c.userId])
    ok = '✅ Новая цель для кардио установлена!'
  } else {
    ok = '✅ Цель установлена (но упражнение не найдено)!'
  }
  c.s.clear()
  await sendTemp(c, ok)
  if (data.category_id) await workoutManageExercisesCat(c, data.category_id)
  else await workoutManageAfterAction(c)
}

async function workoutManageExercisesCat(c, catId) {
  const { s, chatId } = c
  const old = s.temps.workout_temp
  delete s.temps.workout_temp
  if (old) await del(chatId, old)
  const cat = await one('SELECT name FROM exercise_categories WHERE id = ?', [catId ?? null])
  const exercises = (await all('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', [c.userId, catId ?? null])).map(r => [r.id, r.name])
  const msg = await send(chatId, `Упражнения в категории '${cat ? cat.name : 'Категория'}':`, { reply_markup: K.workoutExercisesKeyboard(exercises, catId, 'manage') })
  s.temps.workout_temp = msg.message_id
}

async function workoutRenameExercise(c) {
  c.s.updateData({ renaming_ex_id: parseInt(c.data.split('_')[3], 10) })
  await c.deleteMsg()
  c.s.setState(WorkoutState.renaming_exercise)
  const msg = await c.reply('Введи новое название для категории:', { reply_markup: backKeyboard() })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutRenameExerciseFinish(c) {
  const name = (c.text || '').trim()
  if (name.length < 2) return c.reply('❌ Слишком короткое название. Попробуй ещё раз:')
  const exId = c.s.getData().renaming_ex_id
  c.s.clear()
  await c.deleteMsg()
  if (!exId) return workoutManageAfterAction(c)
  const row = await one('SELECT category_id FROM exercises WHERE id = ?', [exId])
  const catId = row ? row.category_id : null
  try {
    await execute('UPDATE exercises SET name = ? WHERE id = ? AND user_id = ?', [name, exId, c.userId])
  } catch (e) {
    if (!isUniqueViolation(e)) throw e
    await c.reply('❌ Упражнение с таким именем уже существует в этой категории.')
  }
  if (catId) await workoutManageExercisesCat(c, catId)
  else await workoutManageAfterAction(c)
}

async function workoutDeleteExerciseConfirm(c) {
  c.s.updateData({ deleting_ex_id: parseInt(c.data.split('_')[3], 10) })
  await c.deleteMsg()
  c.s.setState(WorkoutState.deleting_exercise_confirm)
  // (sic) The Python bot offered «Пропустить →» here, which never reached «w_ex_delete_yes».
  const msg = await c.reply('⚠️ Ты уверен, что хочешь удалить это упражнение?', { reply_markup: kb(withBack([
    [btn('✅ Да, удалить', 'w_ex_delete_yes'), btn('❌ Нет', 'workout_manage')],
  ])) })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutDeleteExerciseFinish(c) {
  const exId = c.s.getData().deleting_ex_id
  if (!exId) {
    c.s.clear()
    return workoutManageAfterAction(c)
  }
  const row = await one('SELECT category_id FROM exercises WHERE id = ?', [exId])
  const catId = row ? row.category_id : null
  await execute('DELETE FROM exercises WHERE id = ? AND user_id = ?', [exId, c.userId])
  c.s.clear()
  await c.deleteMsg()
  await sendTemp(c, '✅ Упражнение удалено.')
  if (catId) await workoutManageExercisesCat(c, catId)
  else await workoutManageAfterAction(c)
}

// ───────────────────────── history ─────────────────────────

export async function showWorkoutHistoryPage(c, page = 0, editMsgId = null) {
  const { s, userId, chatId } = c
  const rows = await all(`
    SELECT id, date, weekday, session_key, plan_json, status, skip_reason, feedback
    FROM ai_workout_sessions WHERE user_id = ? AND status != 'pending' ORDER BY date DESC
  `, [userId])
  if (!rows.length) {
    const text = 'Тренировок пока нет.'
    if (editMsgId && await tryEdit(chatId, editMsgId, text)) { s.navPush('workout_history'); return }
    const m = await send(chatId, text)
    s.temps.workout_menu = m.message_id
    s.navPush('workout_history')
    return
  }
  const total = rows.length
  page = Math.max(0, Math.min(page, total - 1))
  const text = await ws.formatSessionDetail(rows[page])
  const nav = []
  if (page < total - 1) nav.push(btn('← Раньше', `wh_page_${page + 1}`))
  if (page > 0) nav.push(btn('Позже →', `wh_page_${page - 1}`))
  const rowsKb = []
  if (nav.length) rowsKb.push(nav)
  rowsKb.push([btn(`${total - page}/${total}`, 'wh_noop')])
  const markup = kb(withBack(rowsKb))
  if (editMsgId && await tryEdit(chatId, editMsgId, text, { reply_markup: markup })) return
  const m = await send(chatId, text, { reply_markup: markup })
  s.temps.workout_menu = m.message_id
  s.navPush('workout_history')
}

const DAY_ORDER = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const DAY_NAMES = { monday: 'Пн', tuesday: 'Вт', wednesday: 'Ср', thursday: 'Чт', friday: 'Пт', saturday: 'Сб', sunday: 'Вс' }

export function planDayButtons(planData) {
  const plan = planData.plan || {}
  const cycle = planData.cycle_weeks ?? 1
  const seen = new Set(), buttons = []
  for (let w = 1; w <= cycle; w++) {
    const week = plan[`week_${w}`] || {}
    for (const dk of DAY_ORDER) {
      if (dk in week && !seen.has(dk)) {
        seen.add(dk)
        buttons.push([btn(DAY_NAMES[dk], `wex_day_${dk}`)])
      }
    }
  }
  return buttons
}

export function planDayExercises(planData, dayKey) {
  const plan = planData.plan || {}
  const cycle = planData.cycle_weeks ?? 1
  for (let w = 1; w <= cycle; w++) {
    const exs = (plan[`week_${w}`] || {})[dayKey] || []
    if (exs.length) return exs
  }
  return []
}

async function workoutEditExerciseStart(c) {
  await c.deleteMsg()
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) return
  await del(c.chatId, c.s.temps.workout_menu)
  delete c.s.temps.workout_menu
  const msg = await c.reply('Выбери день тренировки:', { reply_markup: kb(withBack(planDayButtons(planData))) })
  c.s.temps.workout_menu = msg.message_id
  c.s.navPush('wex_days')
  c.s.setState(AIPlanState.editing_plan)
  c.s.updateData({ wp_edit_mode: 'exercise' })
}

async function workoutEditChooseDay(c) {
  const dayKey = c.data.split('_')[2]
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) return c.answer('Нет плана', true)
  const exercises = planDayExercises(planData, dayKey)
  if (!exercises.length) return c.answer('Нет упражнений', true)
  c.s.updateData({ wp_edit_day: dayKey })
  const buttons = exercises.map((ex, i) => [btn(pyVal(pget(ex, 'exercise', pget(ex, 'name', `Упражнение ${i + 1}`))), `wex_ex_${i}`)])
  await tryEdit(c.chatId, c.msg.message_id, 'Выбери упражнение для замены:', { reply_markup: kb(withBack(buttons)) })
  c.s.navPush('wex_ex')
}

async function workoutEditBackToDays(c) {
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) return
  await tryEdit(c.chatId, c.msg.message_id, 'Выбери день тренировки:', { reply_markup: kb(withBack(planDayButtons(planData))) })
  c.s.navPush('wex_days')
}

async function workoutEditChooseExercise(c) {
  const idx = parseInt(c.data.split('_')[2], 10)
  const dayKey = c.s.getData().wp_edit_day ?? 'monday'
  const planData = await repo.getAiPlan(c.userId)
  if (!planData) return
  const exercises = planDayExercises(planData, dayKey)
  if (!(idx < exercises.length)) return c.answer('Упражнение не найдено', true)
  const name = exerciseName(exercises[idx])
  c.s.updateData({ wp_edit_ex_idx: idx, wp_edit_ex_name: name, wp_edit_mode: 'exercise_replace' })
  await tryEdit(c.chatId, c.msg.message_id, `Чем заменить «${pyVal(name)}»?\n\nНапиши название нового упражнения:`)
  c.s.navPush('wex_replace')
}

async function workoutHistory(c) {
  await c.deleteMsg()
  c.s.historyPage = 0
  await showHistoryPage(c)
}

export async function showHistoryPage(c, editMessageId = null) {
  const { s, userId, chatId } = c
  let page = s.historyPage
  const limit = 3
  const allDates = (await all('SELECT DISTINCT date FROM workout_log WHERE user_id = ? ORDER BY date DESC', [userId])).map(r => r.date)
  const totalDays = allDates.length
  const totalPages = totalDays > 0 ? Math.ceil(totalDays / limit) : 1
  if (page >= totalPages && totalPages > 0) {
    page = totalPages - 1
    s.historyPage = page
  }
  let text
  if (!totalDays) {
    text = '📊 История тренировок пока пуста.'
  } else {
    const lines = []
    for (const date of allDates.slice(page * limit, Math.min(page * limit + limit, totalDays))) {
      const dayEx = await all(`
        SELECT wl.exercise_name, wl.sets, wl.reps, wl.weight, wl.distance, wl.duration, ec.name AS cat_name
        FROM workout_log wl LEFT JOIN exercise_categories ec ON wl.category_id = ec.id
        WHERE wl.user_id = ? AND wl.date = ? ORDER BY wl.id
      `, [userId, date])
      lines.push(`\n📅 ${ddmmyyyy(date)}`)
      for (const e of dayEx) {
        let line
        if (e.sets !== null) {
          line = `  💪 ${e.cat_name || 'Без категории'}: ${e.exercise_name} – ${e.sets}х${pyVal(e.reps)}`
          if (e.weight) line += ` (${pyFloat(e.weight)} кг)`
        } else {
          const parts = []
          if (e.distance) parts.push(`${pyFloat(e.distance)} км`)
          if (e.duration) parts.push(`${e.duration} мин`)
          line = `  🚴 ${e.cat_name || 'Кардио'}: ${e.exercise_name} – ` + parts.join(' / ')
        }
        lines.push(line)
      }
    }
    text = '📊 История тренировок\n' + lines.join('\n')
  }
  const nav = []
  if (page > 0) nav.push(btn('⬅️ Предыдущая', 'history_prev'))
  if (page < totalPages - 1) nav.push(btn('Следующая ➡️', 'history_next'))
  const markup = kb(withBack(nav.length ? [nav] : []))
  if (editMessageId) {
    await edit(chatId, editMessageId, text, { reply_markup: markup })
  } else {
    const m = await send(chatId, text, { reply_markup: markup })
    s.temps.workout_history = m.message_id
  }
  s.navPush('history')
}

// ───────────────────────── exercise charts ─────────────────────────

async function doWorkoutCharts(c) {
  const categories = await categoriesOf(c.userId)
  if (!categories.length) {
    await send(c.chatId, '❌ Нет категорий для графиков')
    await showWorkoutMainMenu(c)
    return
  }
  c.s.setState(WorkoutState.choosing_category)
  c.s.updateData({ workout_charts_mode: true })
  const msg = await send(c.chatId, 'Выбери категорию для графика:', { reply_markup: K.workoutCategoriesKeyboard(categories, 'add') })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutChartsChooseCategory(c) {
  const catId = parseInt(c.data.split('_')[3], 10)
  await c.deleteMsg()
  const exercises = (await all('SELECT id, name FROM exercises WHERE user_id = ? AND category_id = ? ORDER BY name', [c.userId, catId])).map(r => [r.id, r.name])
  if (!exercises.length) {
    await c.reply('❌ В этой категории нет упражнений.')
    await showWorkoutMainMenu(c)
    return
  }
  c.s.updateData({ chart_cat_id: catId })
  c.s.setState(WorkoutState.choosing_exercise)
  const msg = await c.reply('Выбери упражнение для графика:', { reply_markup: K.workoutExercisesKeyboard(exercises, catId, 'add') })
  c.s.temps.workout_temp = msg.message_id
}

async function workoutChartsGenerate(c) {
  const exId = parseInt(c.data.split('_')[3], 10)
  await c.deleteMsg()
  c.s.clear()
  try { await api.sendChatAction({ chat_id: c.chatId, action: 'upload_photo' }) } catch { /* noop */ }
  const rows = (await all(`
    SELECT date, sets, reps, weight, distance, duration FROM workout_log
    WHERE user_id = ? AND exercise_name = (SELECT name FROM exercises WHERE id = ?) ORDER BY date
  `, [c.userId, exId])).map(r => r.$)
  const typeRow = await one('SELECT ex_type FROM exercise_categories WHERE id = (SELECT category_id FROM exercises WHERE id = ?)', [exId])
  const exType = typeRow ? typeRow.ex_type : 'strength'
  if (rows.length < 2) {
    await c.reply('❌ Недостаточно данных для графика (нужно минимум 2 записи).')
    await showWorkoutMainMenu(c)
    return
  }
  const png = await renderChart('workout', { user_id: c.userId, rows, ex_type: exType })
  if (png) await sendPhoto(c.userId, png, { caption: '📈 Прогресс упражнения' })
}

async function workoutShowGoal(c) {
  const exId = parseInt(c.data.split('_')[3], 10)
  const row = await one('SELECT name, target_sets, target_reps, target_weight, target_distance, target_duration FROM exercises WHERE id = ? AND user_id = ?', [exId, c.userId])
  if (!row) return c.answer('❌ Упражнение не найдено', true)
  const text = row.target_sets && row.target_reps
    ? `🎯 Цель упражнения *${row.name}*:\n${row.target_sets}×${row.target_reps}` + (row.target_weight ? ` с весом ${pyFloat(row.target_weight)} кг` : '')
    : `🎯 Цель упражнения *${row.name}*:\nДистанция ${pyFloat(row.target_distance)} км за ${pyVal(row.target_duration)} мин`
  await c.reply(text, { parse_mode: 'Markdown' })
}

// ───────────────────────── registration (same order as workouts.py) ─────────────────────────

const S = WorkoutSessionState
const isText = (c) => c.text !== null && c.text !== undefined

export function register() {
  onCallback({ data: 'menu_photo_analysis' }, handlePhotoAnalysisStart)
  onMessage({ photo: true, state: 'waiting_for_photo' }, analyzePhoto)
  onCallback({ data: 'photo_analysis_cancel', state: 'waiting_for_photo' }, photoAnalysisCancel)
  onCallback({ data: 'photo_analysis_back' }, photoAnalysisBack)
  onMessage({ state: 'waiting_for_photo', when: isText }, photoTimeout)
  onCallback({ data: 'menu_workouts' }, handleWorkouts)
  onMessage({ state: WorkoutState.waiting_for_goal }, processWorkoutGoal)
  onCallback({ data: 'menu_workout_add' }, workoutAddMsg)
  onCallback({ data: 'workout_add' }, workoutAddStart)
  onCallback({ data: 'w_back_to_main_from_add' }, workoutBackToMain)
  onCallback({ state: WorkoutState.choosing_category, prefix: 'w_add_cat_' }, workoutAddChooseCategory)
  onCallback({ state: WorkoutState.choosing_exercise, prefix: 'w_add_ex_' }, workoutAddChooseExercise)
  onCallback({ prefix: 'w_manual_' }, workoutManualEnter)
  onMessage({ state: WorkoutState.entering_reps }, workoutEnterReps)
  onMessage({ state: WorkoutState.entering_weight }, workoutEnterWeight)
  onMessage({ state: WorkoutState.entering_distance }, workoutEnterDistance)
  onMessage({ state: WorkoutState.entering_duration }, workoutEnterDuration)
  onCallback({ data: 'w_continue_yes', state: WorkoutState.confirm_continue }, workoutContinueYes)
  onCallback({ prefix: 'w_achieve_goal_' }, workoutAchieveGoal)
  onCallback({ data: 'ws_rest_back' }, backToToday)
  onCallback({ data: 'ws_pick_day' }, wsPickDay)
  onCallback({ prefix: 'ws_day_' }, wsPickDayChosen)
  onCallback({ state: S.viewing_plan, data: 'ws_extra_cancel' }, wsExtraCancel)
  onCallback({ data: 'ws_free_log' }, wsFreeLogStart)
  onMessage({ state: S.free_logging }, wsFreeLogInput)
  onCallback({ data: 'wp_mode_ai' }, wpChooseAi)
  onCallback({ data: 'wp_mode_manual' }, wpChooseManual)
  onCallback({ data: 'wp_back_to_mode' }, wpBackToMode)
  onCallback({ state: AIPlanState.choosing_goal, prefix: 'wp_goal_' }, wpChooseGoal)
  onCallback({ data: 'wp_back_to_goal' }, wpBackToGoal)
  onCallback({ state: AIPlanState.choosing_level, prefix: 'wp_level_' }, wpChooseLevel)
  onCallback({ data: 'wp_back_to_level' }, wpBackToLevel)
  onCallback({ state: AIPlanState.choosing_days_count, prefix: 'wp_days_' }, wpChooseDays)
  onCallback({ state: AIPlanState.entering_extra_notes, data: 'wp_notes_skip' }, wpNotesSkip)
  onMessage({ state: AIPlanState.entering_extra_notes }, wpNotesInput)
  onCallback({ data: 'wp_back_to_days' }, wpBackToDays)
  onCallback({ data: 'wp_plan_regenerate' }, generateAndShowPlan)
  onCallback({ data: 'wp_plan_edit' }, wpPlanEditStart)
  onCallback({ data: 'wp_back_to_review' }, wpBackToReview)
  onMessage({ state: AIPlanState.editing_plan }, wpPlanEditInput)
  onCallback({ data: 'wp_plan_accept' }, wpPlanAccept)
  onMessage({ state: AIPlanState.entering_manual_plan }, wpManualInput)
  onCallback({ data: 'workout_main_ai' }, workoutMainAi)
  onCallback({ data: 'back_to_workout_main' }, backToWorkoutMain)
  onCallback({ state: S.in_exercise, data: 'ws_ex_done' }, wsExerciseDone)
  onCallback({ state: S.in_exercise, data: 'ws_ex_skip' }, wsExerciseSkip)
  onCallback({ state: S.in_exercise, data: 'ws_ex_prev' }, wsExercisePrev)
  onMessage({ state: S.in_exercise }, wsExerciseTextInput)
  onCallback({ state: S.in_exercise, data: 'ws_ex_replace' }, wsExerciseReplace)
  onCallback({ state: S.replacing_exercise, data: 'ws_sub_back' }, wsReplaceBack)
  onCallback({ state: S.replacing_exercise, prefix: 'ws_sub_' }, wsReplaceSuggestion)
  onMessage({ state: S.replacing_exercise }, wsReplaceTextInput)
  onCallback({ state: S.raising_weight, prefix: 'ws_raise_' }, wsRaiseWeight)
  onMessage({ state: S.raising_weight }, wsRaiseWeightCustom)
  onCallback({ data: 'ws_skip_day' }, wsSkipDayStart)
  onCallback({ state: S.skipping_day, data: 'ws_back_to_today' }, wsBackToToday)
  onMessage({ state: S.skipping_day }, wsSkipDayReason)
  onCallback({ data: 'wp_settings' }, wpSettings)
  onCallback({ data: 'wp_reset' }, wpReset)
  onCallback({ data: 'wp_monthly_review' }, wpMonthlyReviewStart)
  onMessage({ state: S.monthly_review }, wpMonthlyReviewInput)
  onCallback({ data: 'wp_review_decline' }, wpReviewDecline)
  onCallback({ data: 'menu_workout_manage' }, workoutManageMsg)
  onCallback({ data: 'wp_edit_plan' }, workoutEditPlanMsg)
  onCallback({ data: 'wp_new_plan' }, workoutNewAiPlanMsg)
  onCallback({ data: 'workout_manage_back' }, workoutManageBack)
  onCallback({ data: 'workout_manage' }, workoutManage)
  onCallback({ data: 'workout_main' }, workoutMainCallback)
  onCallback({ data: 'w_cat_new' }, workoutNewCategory)
  onMessage({ state: WorkoutState.creating_category }, workoutCreateCategory)
  onCallback({ when: c => c.data === 'cat_type_strength' || c.data === 'cat_type_cardio' }, workoutCreateCategoryType)
  onCallback({ prefix: 'w_manage_cat_' }, workoutManageViewCategory)
  onCallback({ prefix: 'w_cat_rename_' }, workoutRenameCategory)
  onMessage({ state: WorkoutState.renaming_category }, workoutRenameCategoryFinish)
  onCallback({ when: c => /^w_cat_delete_\d+$/.test(c.data) }, workoutDeleteCategoryConfirm)
  onCallback({ data: 'w_cat_delete_yes', state: WorkoutState.deleting_category_confirm }, workoutDeleteCategoryFinish)
  onCallback({ when: c => /^w_manage_exercises_\d+$/.test(c.data) }, workoutManageExercises)
  onCallback({ data: 'w_back_to_cats_from_ex' }, workoutBackToCatsFromEx)
  onCallback({ data: 'w_back_to_ex_from_actions' }, workoutManage)
  onCallback({ prefix: 'w_manage_ex_' }, workoutManageViewExercise)
  onCallback({ prefix: 'w_ex_set_goal_' }, workoutSetGoalFromManage)
  onCallback({ when: c => /^w_ex_new_\d+$/.test(c.data) }, workoutNewExercise)
  onMessage({ state: WorkoutState.creating_exercise }, workoutCreateExercise)
  onCallback({ state: WorkoutState.setting_goal_type, data: 'goal_strength' }, setGoalStrength)
  onMessage({ state: WorkoutState.setting_strength_goal }, setStrengthGoalFinish)
  onCallback({ state: WorkoutState.setting_goal_type, data: 'goal_cardio' }, setGoalCardio)
  onMessage({ state: WorkoutState.setting_cardio_goal }, setCardioGoalFinish)
  onCallback({ when: c => /^w_ex_rename_\d+$/.test(c.data) }, workoutRenameExercise)
  onMessage({ state: WorkoutState.renaming_exercise }, workoutRenameExerciseFinish)
  onCallback({ when: c => /^w_ex_delete_\d+$/.test(c.data) }, workoutDeleteExerciseConfirm)
  onCallback({ data: 'w_ex_delete_yes', state: WorkoutState.deleting_exercise_confirm }, workoutDeleteExerciseFinish)
  onMessage({ text: '✏️ Изменить упражнение' }, workoutEditExerciseStart)
  onCallback({ state: AIPlanState.editing_plan, prefix: 'wex_day_' }, workoutEditChooseDay)
  onCallback({ state: AIPlanState.editing_plan, data: 'wex_back_to_days' }, workoutEditBackToDays)
  onCallback({ state: AIPlanState.editing_plan, prefix: 'wex_ex_' }, workoutEditChooseExercise)
  onCallback({ data: 'workout_history' }, workoutHistory)
  onCallback({ prefix: 'wh_page_' }, async (c) => showWorkoutHistoryPage(c, parseInt(c.data.split('_')[2], 10), c.msg.message_id))
  onCallback({ data: 'wh_noop' }, async () => {})
  onCallback({ data: 'workout_history_back' }, async (c) => { await c.deleteMsg(); await showWorkoutMainMenu(c) })
  onCallback({ data: 'history_prev' }, async (c) => { if (c.s.historyPage > 0) c.s.historyPage = c.s.historyPage - 1; await showHistoryPage(c, c.msg.message_id) })
  onCallback({ data: 'history_next' }, async (c) => { c.s.historyPage = c.s.historyPage + 1; await showHistoryPage(c, c.msg.message_id) })
  onCallback({ data: 'workout_charts' }, async (c) => { await c.deleteMsg(); await doWorkoutCharts(c) })
  onCallback({ prefix: 'w_show_goal_' }, workoutShowGoal)
}
