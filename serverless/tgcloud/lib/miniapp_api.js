// trackcheck/web/api.py — the Mini App's JSON API, served through one endpoint
// (endpoints/api.js) instead of HTTP routes. Each handler returns what the
// aiohttp route returned: { status, body: { ok, data } | { ok: false, error, message } }.
// The caller is the user the platform verified (ctx.initData.user).

import * as repo from './repo.js'
import { all, one, execute } from './turso.js'
import { WEEKDAY_KEY, WEEKDAY_RU, WEEKDAY_FROM_KEY } from './config.js'
import { userNow, userToday, isDateStr } from './dates.js'
import { getRankName, getRankEmoji, getSparksForNextRank, pyRound, pyJson, plen, pslice, stripMarkdown } from './util.js'
import * as ai from './ai.js'
import * as ws from './workout_service.js'
import { exerciseName } from './workout_service.js'
import { AUTO_CATEGORIES, ensureRestDayRating, syncDietRatingForToday, syncActivityRatingForToday } from './tracker.js'
import { getPotential, explainSegments } from './potential.js'

export const RU_ERRORS = {
  unauthorized: 'Открой через Telegram — кнопка Mini App.',
  bad_json: 'Не получилось прочитать запрос. Попробуй ещё раз.',
  bad_params: 'Некорректные данные. Проверь ввод.',
  bad_rating: 'Оценка должна быть от 1 до 10.',
  bad_title: 'Название задачи не может быть пустым.',
  bad_deadline: 'Дедлайн — дата в формате ГГГГ-ММ-ДД.',
  bad_repeat: 'Дни повтора: числа 0–6 (Пн–Вс).',
  bad_id: 'Некорректный ID.',
  bad_calories: 'Калории — число больше нуля.',
  bad_macros: 'БЖУ — числа от 0 до 1000 г.',
  bad_session: 'Тренировка не найдена. Начни заново.',
  bad_action: 'Неизвестное действие.',
  bad_exercise: 'Не получилось распознать упражнение.',
  bad_plan: 'План пустой или повреждён.',
  bad_days: 'Дней в неделю: от 1 до 7.',
  too_short: 'Напиши чуть подробнее (от 3 символов).',
  no_workout_today: 'Сегодня отдых — тренировки нет.',
  ai_failed: '❌ ИИ не ответил. Попробуй ещё раз.',
  ai_pending: '⏳ ИИ ещё думает. Нажми ещё раз через пару секунд — ответ уже готовится.',
  no_estimate: 'Не получилось оценить калории — уточни описание или введи вручную.',
  photo_too_big: 'Фото слишком большое (макс 10 МБ).',
  photo_bad: 'Не получилось прочитать фото.',
  bad_weight: 'Вес: число от 20 до 400 кг.',
  bad_fat: 'Процент жира: число от 1 до 70.',
  bad_text: 'Текст слишком короткий или пустой.',
  auto_category: 'Еда и активность оцениваются автоматически — по калориям и тренировке.',
  no_diet_profile: 'Сначала задай норму калорий.',
  bad_profile: 'Проверь данные: вес 20–300 кг, рост 100–250 см, возраст 10–120.',
  bad_target: 'Цель: от 0,1 до 100 кг за 7–730 дней.',
  bad_day: 'Этого дня нет в плане.',
  session_exists: 'На сегодня тренировка уже есть.',
  bad_increment: 'Прибавка — число от 0 до 100 кг.',
  no_body: 'На фото не видно тела. Пришли фото в полный рост или по пояс.',
}

const ok = (data) => ({ status: 200, body: { ok: true, data } })
const err = (code, status = 400) => ({ status, body: { ok: false, error: code, message: RU_ERRORS[code] ?? code } })
/** Plain {ok:false,error} — routes that answered without a message in Python. */
const bare = (code, status = 400) => ({ status, body: { ok: false, error: code } })

/** Python float()/int() on JSON values: NaN where Python raises. */
function toFloat(v) {
  if (typeof v === 'number') return v
  if (typeof v === 'boolean') return v ? 1 : 0
  if (typeof v === 'string' && /^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*$/.test(v)) return parseFloat(v)
  if (typeof v === 'string' && /^\s*[+-]?(inf|infinity)\s*$/i.test(v)) return v.includes('-') ? -Infinity : Infinity
  return NaN
}
function toInt(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? Math.trunc(v) : NaN
  if (typeof v === 'boolean') return v ? 1 : 0
  if (typeof v === 'string' && /^\s*[+-]?\d+\s*$/.test(v)) return parseInt(v, 10)
  return NaN
}
const str = (v) => (typeof v === 'string' ? v : v == null ? '' : String(v))
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)

// ---- routes ----

async function me(u) {
  const userId = u.id
  try { await ensureRestDayRating(userId) } catch (e) { console.warn('[API me] rest-day rating', e.message) }
  const rank = await repo.getOrCreateRankData(userId)
  const [sparksNeeded, nextTotal] = getSparksForNextRank(rank.current_rank, rank.total_sparks)
  const profile = await repo.getDietProfile(userId)
  return ok({
    id: userId,
    name: await repo.getUserName(userId),
    today_ratings: await repo.getTodayRatings(userId),
    workout: await repo.getOrCreateWorkoutData(userId),
    rank: { ...rank, name: getRankName(rank.current_rank), emoji: getRankEmoji(rank.current_rank), sparks_needed: sparksNeeded, next_total: nextTotal },
    streak: await repo.getStreak(userId),
    diet: {
      configured: profile !== null,
      today_calories: profile ? await repo.getTodayCalories(userId) : 0,
      daily_goal: profile ? profile.daily_calories : 0,
    },
    body_score: await repo.getLastBodyScore(userId),
  })
}

async function ratingsGet(u) { return ok(await repo.getTodayRatings(u.id)) }

async function ratingsPost(u, body) {
  const category = str(body.category).trim()
  const rating = toInt(body.rating)
  if (Number.isNaN(rating)) return bare('bad_rating')
  if (!['сон', 'еда', 'активность', 'зависание', 'настрой'].includes(category) || !(rating >= 1 && rating <= 10)) return bare('bad_params')
  if (AUTO_CATEGORIES.includes(category)) return err('auto_category')
  await repo.saveUserSettings(u.id, u.username || '', u.first_name || '')
  await repo.updateStreak(u.id)
  await repo.saveRating(u.id, category, rating, await userToday(u.id))
  let sparkAwarded = false
  if (await repo.checkAllCategoriesCompleted(u.id)) {
    const [s] = await repo.addSpark(u.id, 'categories')
    sparkAwarded = !!s
  }
  return ok({ ratings: await repo.getTodayRatings(u.id), spark_awarded: sparkAwarded })
}

async function tasksGet(u) { return ok(await repo.getAllActiveTasks(u.id)) }

async function tasksPost(u, body) {
  const title = pslice(str(body.title).trim(), 0, 200)
  if (!title) return bare('bad_title')
  const isPriority = !!(body.is_priority ?? false)
  const deadline = body.deadline || null
  if (deadline && !isDateStr(deadline)) return bare('bad_deadline')
  let repeat = body.repeat_days || null
  if (repeat !== null) {
    const ok06 = (x) => /^\d+$/.test(String(x)) && Number(x) >= 0 && Number(x) <= 6
    if (Array.isArray(repeat)) repeat = repeat.filter(ok06).map(x => String(parseInt(x, 10))).join(',') || null
    else if (typeof repeat === 'string') repeat = repeat.split(',').map(p => p.trim()).filter(ok06).join(',') || null
    else return bare('bad_repeat')
  }
  await repo.addTask(u.id, title, isPriority, deadline, repeat)
  return ok({ created: true })
}

async function taskDone(u, _b, _q, p) {
  const id = toInt(p.task_id)
  if (Number.isNaN(id)) return bare('bad_id')
  await repo.completeTask(id, u.id)
  return ok({ done: true })
}

async function taskDelete(u, _b, _q, p) {
  const id = toInt(p.task_id)
  if (Number.isNaN(id)) return bare('bad_id')
  await repo.deleteTask(id, u.id)
  return ok({ deleted: true })
}

async function dietGet(u) {
  const profile = await repo.getDietProfile(u.id)
  const log = (await repo.getTodayFoodLog(u.id)).map(r => ({
    meal: r.meal_type, description: r.food_description, calories: r.calories, protein: r.protein, fat: r.fat, carbs: r.carbs,
  }))
  return ok({
    profile,
    today_calories: await repo.getTodayCalories(u.id),
    today_macros: await repo.getTodayMacros(u.id),
    macro_goals: await repo.getMacroGoals(u.id, profile),
    today_log: log,
  })
}

async function dietLogPost(u, body) {
  const description = pslice(str(body.description).trim(), 0, 300)
  const calories = toFloat(body.calories ?? 0)
  if (Number.isNaN(calories)) return bare('bad_calories')
  if (!description || !(calories > 0 && calories <= 10000)) return bare('bad_params')
  let macros = null
  if (['protein', 'fat', 'carbs'].some(k => body[k] !== undefined && body[k] !== null)) {
    macros = Object.fromEntries(['protein', 'fat', 'carbs'].map(k => [k, toFloat(body[k])]))
    if (Object.values(macros).some(Number.isNaN)) return bare('bad_macros')
    if (!Object.values(macros).every(v => Number.isFinite(v) && v >= 0 && v <= 1000)) return bare('bad_macros')
  }
  const meal = pslice(str(body.meal || 'Еда').trim(), 0, 50)
  if (!(await repo.getDietProfile(u.id))) return err('no_diet_profile')
  await repo.saveFoodLog(u.id, meal, description, calories, macros?.protein ?? null, macros?.fat ?? null, macros?.carbs ?? null)
  await syncDietRatingForToday(u.id)
  return ok({ today_calories: await repo.getTodayCalories(u.id) })
}

async function dietHistory(u) { return ok({ foods: await repo.getFoodHistory(u.id) }) }

async function workoutGet(u) {
  const userId = u.id
  const planData = await repo.getAiPlan(userId)
  if (!planData) return ok({ has_plan: false, workout: await repo.getOrCreateWorkoutData(userId) })
  const scheduled = (await repo.getTodayPlan(planData, userId)) || []
  const session = await repo.getTodaySession(userId)
  const logs = session ? await repo.getSessionExerciseLogs(session.id) : []
  let todayEx = scheduled
  let extra = null
  if (session) {
    todayEx = Array.isArray(session.plan) ? session.plan : Object.values(session.plan)
    const parts = session.session_key.split('_')
    const dayKey = parts.length > 2 ? parts.slice(2).join('_') : parts[parts.length - 1]
    const now = await userNow(userId)
    if (session.session_key === 'free') extra = { kind: 'free', label: 'Своя тренировка' }
    else if (dayKey !== WEEKDAY_KEY[now.weekday]) extra = { kind: 'plan_day', label: WEEKDAY_RU[WEEKDAY_FROM_KEY[dayKey]] ?? dayKey }
  }
  const [doneCount, weekGoal] = await repo.getWeeklyWorkoutProgress(userId)
  const [nextDate, nextDay] = await repo.getNextTrainingDay(planData, userId)
  return ok({
    has_plan: true,
    mode: planData.mode, goal: planData.goal, level: planData.level, days_per_week: planData.days_per_week,
    plan: planData.plan,
    today_exercises: todayEx,
    is_rest_day: todayEx.length === 0,
    extra,
    plan_days: scheduled.length ? [] : await ws.planDayOptions(planData, userId),
    session: session ? { id: session.id, status: session.status } : null,
    logs: logs.map(l => ({ exercise_name: l.exercise_name, status: l.status, result: l.result ?? null, planned: l.planned ?? null })),
    week_progress: { done: doneCount, goal: weekGoal },
    next: nextDate ? { date: nextDate, day: nextDay } : null,
    workout: await repo.getOrCreateWorkoutData(userId),
  })
}

async function workoutStart(u) {
  const planData = await repo.getAiPlan(u.id)
  const session = planData ? await repo.createTodaySession(u.id, planData) : null
  if (!session) return bare('no_workout_today', 404)
  return ok({ session_id: session.id, status: session.status })
}

async function ownSession(userId, sessionId) {
  return !!(await one('SELECT id FROM ai_workout_sessions WHERE id = ? AND user_id = ?', [sessionId, userId]))
}

async function workoutLog(u, body) {
  const sessionId = toInt(body.session_id ?? 0)
  if (Number.isNaN(sessionId)) return bare('bad_session')
  const action = str(body.action).trim()
  if (action !== 'done' && action !== 'skip') return bare('bad_action')
  const ex = isObj(body.exercise) ? body.exercise : {}
  const exName = pslice(str(ex.exercise || ex.name).trim(), 0, 200)
  if (!exName) return bare('bad_exercise')
  if (!(await ownSession(u.id, sessionId))) return bare('bad_session', 404)
  let raise = null
  if (action === 'done') {
    raise = ws.planRaiseTarget(ex, body.result ?? null)
    const result = body.result || { sets_done: ex.sets ?? null, reps_done: ex.reps ?? null, weight_done: ex.weight ?? null, completed: true }
    await execute(`INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, result_json, status)
      VALUES (?, ?, ?, ?, ?, 'done')`, [sessionId, u.id, exName, pyJson(ex), pyJson(result)])
  } else {
    await execute(`INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, status)
      VALUES (?, ?, ?, ?, 'skipped')`, [sessionId, u.id, exName, pyJson(ex)])
  }
  return ok({ logged: true, raise })
}

async function workoutUndo(u, body) {
  const ex = body.exercise || {}
  if (!isObj(ex) || !(ex.exercise || ex.name)) return err('bad_exercise')
  const name = exerciseName(ex)
  const sessionId = toInt(body.session_id)
  if (Number.isNaN(sessionId)) return err('bad_session')
  const row = await one('SELECT status FROM ai_workout_sessions WHERE id = ? AND user_id = ?', [sessionId, u.id])
  if (!row || row.status === 'done') return err('bad_session', 404)
  const logs = await all('SELECT id, exercise_name, planned_json FROM ai_exercise_logs WHERE session_id = ? AND user_id = ?', [sessionId, u.id])
  const ids = []
  for (const l of logs) {
    let planned = null
    try { planned = l.planned_json ? JSON.parse(l.planned_json) : null } catch { planned = null }
    const key = isObj(planned) ? exerciseName(planned) : l.exercise_name
    if (key === name) ids.push(l.id)
  }
  for (const id of ids) await execute('DELETE FROM ai_exercise_logs WHERE id = ?', [id])
  return ok({ removed: ids.length })
}

async function workoutFinish(u, body) {
  const sessionId = toInt(body.session_id ?? 0)
  if (Number.isNaN(sessionId)) return bare('bad_session')
  const row = await one('SELECT status FROM ai_workout_sessions WHERE id = ? AND user_id = ?', [sessionId, u.id])
  if (!row) return bare('bad_session', 404)
  let sparkOk = false, rankUp = false, newRank = null
  if (row.status !== 'done') {
    await execute("UPDATE ai_workout_sessions SET status='done', completed_at=? WHERE id=?", [await userToday(u.id), sessionId])
    await repo.addWorkout(u.id);
    [sparkOk, , rankUp, , newRank] = await repo.addSpark(u.id, 'workout')
    await repo.updateStreak(u.id)
  }
  await syncActivityRatingForToday(u.id)
  const logs = await repo.getSessionExerciseLogs(sessionId)
  return ok({
    done: logs.filter(l => l.status === 'done').length,
    skipped: logs.filter(l => l.status === 'skipped').length,
    spark_awarded: !!sparkOk, rank_up: !!rankUp, new_rank: newRank,
    name: await repo.getUserName(u.id),
  })
}

async function workoutGenerate(u, body) {
  const goal = pslice(str(body.goal).trim(), 0, 100)
  const level = pslice(str(body.level).trim(), 0, 50)
  const days = toInt(body.days ?? 3)
  if (Number.isNaN(days)) return bare('bad_days')
  const notes = pslice(str(body.notes).trim(), 0, 500)
  if (!goal || !level || !(days >= 1 && days <= 7)) return bare('bad_params')
  const plan = await ai.geminiGeneratePlan(goal, level, days, notes, { userId: u.id })
  if (plan && plan.pending) return err('ai_pending', 503)
  if (!plan) return bare('ai_failed', 502)
  return ok({ plan })
}

async function workoutSavePlan(u, body) {
  const plan = body.plan
  if (!isObj(plan) || !Object.keys(plan).length) return bare('bad_plan')
  const mode = pslice(str(body.mode || 'ai').trim(), 0, 10)
  const goal = pslice(str(body.goal).trim(), 0, 100)
  const level = pslice(str(body.level).trim(), 0, 50)
  let days = toInt(body.days ?? 3)
  if (Number.isNaN(days)) days = 3
  days = Math.max(1, Math.min(days, 7))
  let cycle = toInt(plan.cycle_weeks ?? 1)
  cycle = Number.isNaN(cycle) ? 1 : Math.max(1, Math.min(cycle, 12))
  await repo.deleteAllWorkoutData(u.id)
  await repo.saveAiPlan(u.id, mode, goal, level, days, plan, cycle)
  return ok({ saved: true })
}

async function workoutHistory(u, _b, q) {
  let limit = toInt(q.limit ?? '10')
  if (Number.isNaN(limit)) limit = 10
  limit = Math.max(1, Math.min(limit, 30))
  const rows = await all('SELECT id, date, session_key, status FROM ai_workout_sessions WHERE user_id = ? ORDER BY date DESC LIMIT ?', [u.id, limit])
  const out = []
  for (const r of rows) {
    const logs = await repo.getSessionExerciseLogs(r.id)
    out.push({
      date: r.date, session_key: r.session_key, status: r.status,
      done: logs.filter(l => l.status === 'done').length,
      skipped: logs.filter(l => l.status === 'skipped').length,
      exercises: logs.map(l => ({ name: l.exercise_name, status: l.status, planned: l.planned ?? null, result: l.result ?? null })),
    })
  }
  return ok(out)
}

/** Check answer: the Mini App used to stream it; here it comes in one piece. */
async function aiAnswer(u, prompt) {
  const r = await ai.generate(prompt, { maxTokens: 8192, userId: u.id })
  if (r.pending) return err('ai_pending', 503)
  if (!r.text) return bare('ai_failed', 502)
  const answer = stripMarkdown(r.text)
  await repo.saveLastAiAnswer(u.id, answer)
  return ok({ answer })
}

async function aiAsk(u, body) {
  const question = pslice(str(body.question).trim(), 0, 2000)
  if (plen(question) < 3) return bare('too_short')
  const name = await repo.getUserName(u.id, u.first_name || 'друг')
  return aiAnswer(u, ai.checkQuestionPrompt(name, await ai.getFullContextForAi(u.id), question))
}

async function aiAdvice(u) {
  const name = await repo.getUserName(u.id, u.first_name || 'друг')
  return aiAnswer(u, ai.checkAdvicePrompt(name, await ai.getFullContextForAi(u.id)))
}

async function bodyGet(u) {
  const row = await one('SELECT body_fat FROM body_fat_log WHERE user_id = ? ORDER BY date DESC LIMIT 1', [u.id])
  return ok({ weight: await repo.getLastWeight(u.id), body_fat: row ? row.body_fat : null })
}

async function bodyPost(u, body) {
  let weight = body.weight ?? null, fat = body.body_fat ?? null
  if (weight === null && fat === null) return err('bad_params')
  weight = weight === null ? null : toFloat(weight)
  fat = fat === null ? null : toFloat(fat)
  if (Number.isNaN(weight) || Number.isNaN(fat)) return err('bad_params')
  if (weight !== null && !(weight >= 20 && weight <= 400)) return err('bad_weight')
  if (fat !== null && !(fat >= 1 && fat <= 70)) return err('bad_fat')
  if (weight !== null) await repo.saveWeightLog(u.id, weight)
  if (fat !== null) await repo.saveBodyFat(u.id, fat)
  return ok({ saved: true })
}

async function bodyScoreGet(u) { return ok(await repo.getLastBodyScore(u.id)) }

const MAX_PHOTO_BYTES = 10 * 1024 * 1024

/** body.photo_b64 (the Mini App downsizes it) → bytes | error code */
function readPhoto(body) {
  if (typeof body.photo_b64 !== 'string' || !body.photo_b64) return [null, 'photo_bad']
  let bytes
  try { bytes = ai.fromBase64(body.photo_b64.replace(/^data:[^,]*,/, '')) } catch { return [null, 'photo_bad'] }
  if (!bytes.length) return [null, 'photo_bad']
  if (bytes.length > MAX_PHOTO_BYTES) return [null, 'photo_too_big']
  return [bytes, null]
}

async function bodyScorePost(u, body) {
  const [image, error] = readPhoto(body)
  if (error) return err(error)
  const result = await ai.rateBodyPhoto(image, { userId: u.id })
  if (result && result.pending) return err('ai_pending', 503)
  if (result === null) return err('ai_failed', 502)
  if (result.error === ai.NO_BODY) return err('no_body')
  return ok(await repo.saveBodyScore(u.id, result))
}

async function dietProfilePost(u, body) {
  const weight = toFloat(body.weight), height = toFloat(body.height), age = toInt(body.age), activity = toFloat(body.activity)
  if ([weight, height, age, activity].some(Number.isNaN)) return err('bad_profile')
  const gender = { male: 'мужской', female: 'женский' }[body.gender]
  const goal = body.goal
  if (![weight, height, activity].every(Number.isFinite) || !(weight >= 20 && weight <= 300) || !(height >= 100 && height <= 250)
    || !(age >= 10 && age <= 120) || !gender || ![1.2, 1.375, 1.55, 1.725, 1.9].includes(activity)
    || !['loss', 'maintain', 'gain'].includes(goal)) return err('bad_profile')
  let change = 0.0, days = 30
  if (goal !== 'maintain') {
    change = toFloat(body.change); days = toInt(body.days)
    if (Number.isNaN(change) || Number.isNaN(days)) return err('bad_target')
    if (!Number.isFinite(change) || !(change >= 0.1 && change <= 100) || !(days >= 7 && days <= 730)) return err('bad_target')
  }
  const tdee = repo.calculateTdee(repo.calculateBmr(weight, height, age, gender), activity)
  const [daily, warning] = repo.calculateDailyCalories(tdee, goal, change, days, gender)
  if (!body.preview) {
    await repo.saveDietProfile(u.id, { weight, height, age, gender, activity_level: activity, goal_type: goal,
      target_weight_change: change, target_days: days, daily_calories: daily })
  }
  return ok({ daily_calories: pyRound(daily), warning: warning === 'ok' ? null : warning, saved: !body.preview })
}

const nutritionJson = (n) => ({
  calories: Math.trunc(pyRound(n.calories)),
  protein: n.protein === null ? null : pyRound(n.protein),
  fat: n.fat === null ? null : pyRound(n.fat),
  carbs: n.carbs === null ? null : pyRound(n.carbs),
})

async function dietPhoto(u, body) {
  if (!(await repo.getDietProfile(u.id))) return err('no_diet_profile')
  const [image, error] = readPhoto(body)
  if (error) return err(error)
  const r = await ai.generate(ai.FOOD_PHOTO_PROMPT, { maxTokens: 512, image, thinkOff: true, userId: u.id })
  if (r.pending) return err('ai_pending', 503)
  if (!r.text) return err('ai_failed', 502)
  const [description, nutrition] = ai.parseFoodPhoto(r.text)
  if (!nutrition) {
    return ok({ description, calories: null, protein: null, fat: null, carbs: null, needs_manual: true, raw: r.text.slice(0, 200) })
  }
  return ok({ description, ...nutritionJson(nutrition), needs_manual: false })
}

async function dietEstimate(u, body) {
  if (!(await repo.getDietProfile(u.id))) return err('no_diet_profile')
  const description = pslice(str(body.description).trim(), 0, 300)
  if (plen(description) < 3) return err('too_short')
  const r = await ai.generate(ai.foodCaloriesPrompt(description), { maxTokens: 100, thinkOff: true, userId: u.id })
  if (r.pending) return err('ai_pending', 503)
  const nutrition = ai.parseFoodEstimate(r.text)
  if (!nutrition) return err('no_estimate', 502)
  return ok(nutritionJson(nutrition))
}

async function workoutParsePlan(u, body) {
  let raw = str(body.text).trim()
  if (plen(raw) < 10) return err('bad_text')
  raw = pslice(raw, 0, 20000)
  let plan = await ai.geminiParseManualPlan(raw, { userId: u.id, waitMs: 16000 })
  if (plan && plan.pending) return err('ai_pending', 503)
  if (!plan) plan = await ai.fallbackParsePlan(raw, { userId: u.id, waitMs: 9000 })
  if (plan && plan.pending) return err('ai_pending', 503)
  if (!plan) return err('ai_failed', 502)
  return ok({ plan })
}

async function workoutLogText(u, body) {
  const sessionId = toInt(body.session_id ?? 0)
  if (Number.isNaN(sessionId)) return err('bad_session')
  const ex = isObj(body.exercise) ? body.exercise : {}
  const exName = pslice(str(ex.exercise || ex.name).trim(), 0, 200)
  const raw = pslice(str(body.text).trim(), 0, 500)
  if (!exName) return err('bad_exercise')
  if (plen(raw) < 1) return err('bad_text')
  if (!(await ownSession(u.id, sessionId))) return err('bad_session', 404)
  const result = await ai.geminiParseExerciseResult(ex, raw, { userId: u.id })
  await execute(`INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, raw_input, result_json, status)
    VALUES (?, ?, ?, ?, ?, ?, 'done')`, [sessionId, u.id, exName, pyJson(ex), raw, pyJson(result)])
  return ok({ result, raise: ws.planRaiseTarget(ex, result) })
}

async function workoutExtra(u, body) {
  const day = str(body.day)
  const planData = await repo.getAiPlan(u.id)
  if (!planData) return err('bad_plan')
  const [session, error] = await ws.startPlanDay(u.id, planData, day)
  if (error) return err(error, error === 'session_exists' ? 409 : 400)
  return ok({ session_id: session.id })
}

async function workoutExtraCancel(u) {
  const session = await repo.getTodaySession(u.id)
  if (!session || session.status !== 'pending') return err('bad_session', 404)
  const parts = session.session_key.split('_')
  const dayKey = parts.length > 2 ? parts.slice(2).join('_') : parts[parts.length - 1]
  if (dayKey === WEEKDAY_KEY[(await userNow(u.id)).weekday]) return err('bad_session', 404)
  await repo.deleteSession(u.id, session.id)
  return ok({ cancelled: true })
}

async function workoutFree(u, body) {
  const raw = pslice(str(body.text).trim(), 0, 1000)
  if (plen(raw) < 3) return err('too_short')
  const items = await ai.geminiParseFreeWorkout(raw, { userId: u.id })
  if (!items.length) return err('bad_exercise')
  const [session, results] = await ws.saveFreeWorkout(u.id, items, raw)
  if (!session) return err('session_exists', 409)
  const [sparkOk, rankUp, newRank] = await ws.countWorkout(u.id)
  await syncActivityRatingForToday(u.id)
  return ok({ session_id: session.id, logs: results, spark_awarded: !!sparkOk, rank_up: !!rankUp, new_rank: newRank })
}

async function workoutSubstitutions(u, _b, q) {
  const name = pslice(str(q.exercise).trim(), 0, 200)
  if (!name) return err('bad_exercise')
  return ok({ suggestions: await ws.substitutionSuggestions(u.id, name) })
}

async function workoutReplace(u, body) {
  const ex = body.exercise || {}
  if (!isObj(ex) || !(ex.exercise || ex.name)) return err('bad_exercise')
  const sessionId = toInt(body.session_id)
  if (Number.isNaN(sessionId) || !(await ownSession(u.id, sessionId))) return err('bad_session', 404)
  if (body.sub_id !== undefined && body.sub_id !== null) {
    const subId = toInt(body.sub_id)
    if (Number.isNaN(subId)) return err('bad_id')
    const sub = await repo.getExerciseSubstitution(u.id, subId)
    if (!sub) return err('bad_id', 404)
    const [result, raise] = await ws.logSubstitutionRepeat(u.id, sessionId, ex, sub)
    return ok({ logs: [{ exercise_name: sub.substitute_name, result }], raise })
  }
  const raw = pslice(str(body.text).trim(), 0, 500)
  if (!raw) return err('bad_text')
  const items = await ai.geminiParseFreeWorkout(raw, { userId: u.id })
  if (!items.length) return err('bad_exercise')
  const [results, raise] = await ws.logSubstitutionItems(u.id, sessionId, ex, items, raw)
  return ok({ logs: results, raise })
}

async function workoutRaise(u, body) {
  const target = isObj(body.target) ? body.target : {}
  const increment = toFloat(String(body.increment).replace(',', '.'))
  const valid = !Number.isNaN(increment) && !Number.isNaN(toFloat(target.weight))
    && increment > 0 && increment <= 100 && ['plan', 'sub'].includes(target.kind)
    && (target.kind === 'plan' || toInt(target.sub_id) > 0)
  if (!valid) return err('bad_increment')
  return ok({ weight: await ws.applyWeightRaise(u.id, target, increment) })
}

async function workoutReview(u) {
  const planData = await repo.getAiPlan(u.id)
  if (!planData) return err('bad_plan', 404)
  const rows = await all(`SELECT id, date, session_key, plan_json FROM ai_workout_sessions
    WHERE user_id = ? AND status = 'done' ORDER BY date DESC LIMIT 10`, [u.id])
  const sessions = []
  for (const r of rows) {
    sessions.push({
      date: r.date, session_key: r.session_key, plan: JSON.parse(r.plan_json),
      logs: (await repo.getSessionExerciseLogs(r.id)).map(l => ({ exercise: l.exercise_name, result: l.result ?? null, status: l.status })),
    })
  }
  const review = await ai.geminiMonthlyReview(planData.plan, sessions, { userId: u.id })
  if (review === null) return err(ai.friendlyAiError().startsWith('⏳') ? 'ai_pending' : 'ai_failed', ai.friendlyAiError().startsWith('⏳') ? 503 : 502)
  return ok(review)
}

async function workoutApplyReview(u, body) {
  const accepted = body.accepted
  if (!Array.isArray(accepted) || !accepted.length) return err('bad_params')
  const planData = await repo.getAiPlan(u.id)
  if (!planData) return err('bad_plan', 404)
  const plan = planData.plan
  let applied = 0
  for (const ch of accepted) {
    if (!isObj(ch)) continue
    const { week, day, old_exercise: oldName, new_exercise: newName } = ch
    if (![week, day, oldName, newName].every(x => typeof x === 'string')) continue
    const lst = (plan[week] || {})[day]
    if (!Array.isArray(lst)) continue
    for (const ex of lst) {
      if (ws.pget(ex, 'exercise', ex.name) === oldName) {
        ex.exercise = newName
        if ('name' in ex) ex.name = newName
        applied++
        break
      }
    }
  }
  if (applied) await repo.updatePlanJson(u.id, plan)
  return ok({ applied })
}

async function aiLast(u) { return ok({ answer: await repo.getLastAiAnswer(u.id) }) }

async function statsGet(u, _b, q) {
  let days = toInt(q.days ?? '7')
  if (Number.isNaN(days)) days = 7
  days = Math.max(1, Math.min(days, 30))
  const byDate = {}
  for (const r of await repo.getDailyRatings(u.id, days)) (byDate[r.day_date] ||= {})[r.category] = r.rating
  const rank = await repo.getOrCreateRankData(u.id)
  return ok({
    days,
    daily: Object.keys(byDate).sort().map(d => ({ date: d, ratings: byDate[d] })),
    rank: { ...rank, name: getRankName(rank.current_rank), emoji: getRankEmoji(rank.current_rank) },
    streak: await repo.getStreak(u.id),
    workout: await repo.getOrCreateWorkoutData(u.id),
    potential: await getPotential(u.id, days),
  })
}

async function statsNotes(u, _b, q) {
  let days = toInt(q.days ?? '7')
  days = Number.isNaN(days) ? 7 : Math.max(1, Math.min(days, 30))
  return ok({ segments: await explainSegments(u.id, days) })
}

// [method, pattern, handler] — the same table as register_api_routes()
const ROUTES = [
  ['GET', '/api/me', me],
  ['GET', '/api/ratings', ratingsGet],
  ['POST', '/api/ratings', ratingsPost],
  ['GET', '/api/tasks', tasksGet],
  ['POST', '/api/tasks', tasksPost],
  ['POST', '/api/tasks/{task_id}/done', taskDone],
  ['DELETE', '/api/tasks/{task_id}', taskDelete],
  ['GET', '/api/diet', dietGet],
  ['POST', '/api/diet/log', dietLogPost],
  ['GET', '/api/diet/history', dietHistory],
  ['POST', '/api/diet/photo', dietPhoto],
  ['POST', '/api/diet/estimate', dietEstimate],
  ['POST', '/api/diet/profile', dietProfilePost],
  ['GET', '/api/body', bodyGet],
  ['POST', '/api/body', bodyPost],
  ['GET', '/api/body/score', bodyScoreGet],
  ['POST', '/api/body/score', bodyScorePost],
  ['GET', '/api/stats', statsGet],
  ['GET', '/api/stats/notes', statsNotes],
  ['GET', '/api/workout', workoutGet],
  ['POST', '/api/workout/start', workoutStart],
  ['POST', '/api/workout/log', workoutLog],
  ['POST', '/api/workout/log-text', workoutLogText],
  ['POST', '/api/workout/undo', workoutUndo],
  ['POST', '/api/workout/finish', workoutFinish],
  ['POST', '/api/workout/extra', workoutExtra],
  ['POST', '/api/workout/extra/cancel', workoutExtraCancel],
  ['POST', '/api/workout/free', workoutFree],
  ['GET', '/api/workout/substitutions', workoutSubstitutions],
  ['POST', '/api/workout/replace', workoutReplace],
  ['POST', '/api/workout/raise', workoutRaise],
  ['POST', '/api/workout/generate', workoutGenerate],
  ['POST', '/api/workout/plan', workoutSavePlan],
  ['POST', '/api/workout/parse-plan', workoutParsePlan],
  ['POST', '/api/workout/review', workoutReview],
  ['POST', '/api/workout/apply-review', workoutApplyReview],
  ['GET', '/api/workout/history', workoutHistory],
  ['POST', '/api/ai/ask', aiAsk],
  ['POST', '/api/ai/advice', aiAdvice],
  ['GET', '/api/ai/last', aiLast],
].map(([method, pattern, fn]) => {
  const names = []
  const re = new RegExp('^' + pattern.replace(/\{(\w+)\}/g, (_, n) => { names.push(n); return '([^/]+)' }) + '$')
  return { method, re, names, fn }
})

/** input: { method, path, body } with the query string inside path. */
export async function handleApi(user, input) {
  const method = String(input.method || 'GET').toUpperCase()
  const [path, qs = ''] = String(input.path || '').split('?')
  const query = {}
  for (const pair of qs.split('&').filter(Boolean)) {
    const [k, v = ''] = pair.split('=')
    query[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, ' '))
  }
  let matchedPath = false
  for (const r of ROUTES) {
    const m = r.re.exec(path)
    if (!m) continue
    matchedPath = true
    if (r.method !== method) continue
    const params = Object.fromEntries(r.names.map((n, i) => [n, decodeURIComponent(m[i + 1])]))
    let body = input.body
    if (method === 'POST' && (body === undefined || body === null || typeof body !== 'object' || Array.isArray(body))) {
      return bare('bad_json')
    }
    return r.fn(user, body || {}, query, params)
  }
  return matchedPath ? bare('method_not_allowed', 405) : bare('not_found', 404)
}

