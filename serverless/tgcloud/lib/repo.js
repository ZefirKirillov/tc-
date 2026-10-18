// trackcheck/database/repositories.py over Turso.

import { execute, one, all, isUniqueViolation } from './turso.js'
import { SPARK_FOR_CATEGORIES, SPARK_FOR_WORKOUT, WEEKDAY_KEY, WEEKDAY_RU, MAX_SPARKS_PER_DAY } from './config.js'
import { userNow, userToday, addDays, daysBetween, weekdayOf, daysInMonth, ymd, isDateStr, ddmm, weekStart } from './dates.js'
import { getCurrentRank, pyRound, pyJson } from './util.js'

export const VALID_CATEGORIES = ['сон', 'еда', 'активность', 'зависание', 'настрой']

// ---- users ----

const nameCache = new Map()

export async function saveUserSettings(userId, username, firstName) {
  // last_active_date is owned by updateStreak()/getStreak() — never stamped here.
  await execute(`
    INSERT INTO user_settings (user_id, username, first_name, last_active_date)
    VALUES (?, ?, ?, NULL)
    ON CONFLICT(user_id) DO UPDATE SET
      username = excluded.username,
      first_name = excluded.first_name
  `, [userId, username ?? null, firstName ?? null])
  if (firstName) nameCache.set(userId, firstName)
}

export async function getUserName(userId, fallback = null) {
  const cached = nameCache.get(userId)
  if (cached) return cached
  const row = await one('SELECT first_name FROM user_settings WHERE user_id = ?', [userId])
  if (row && row.first_name) {
    nameCache.set(userId, row.first_name)
    return row.first_name
  }
  return fallback || 'друг'
}

export async function userExists(userId) {
  return !!(await one('SELECT first_name FROM user_settings WHERE user_id = ?', [userId]))
}

export async function updateStreak(userId) {
  const today = await userToday(userId)
  const yesterday = addDays(today, -1)
  const row = await one('SELECT streak_days, last_active_date FROM user_settings WHERE user_id = ?', [userId])
  if (!row) return
  let streak = row.streak_days || 0
  if (row.last_active_date === yesterday) streak += 1
  else if (row.last_active_date !== today) streak = 1
  await execute('UPDATE user_settings SET streak_days = ?, last_active_date = ? WHERE user_id = ?', [streak, today, userId])
}

export async function getStreak(userId) {
  const today = await userToday(userId)
  const yesterday = addDays(today, -1)
  const row = await one('SELECT streak_days, last_active_date FROM user_settings WHERE user_id = ?', [userId])
  if (!row) return 0
  if (row.last_active_date !== today && row.last_active_date !== yesterday) {
    if (row.last_active_date != null) await execute('UPDATE user_settings SET streak_days = 0 WHERE user_id = ?', [userId])
    return 0
  }
  return row.streak_days || 0
}

// ---- ratings ----

export async function saveRating(userId, category, rating, date) {
  await execute(`
    INSERT INTO ratings (user_id, category, rating, day_date) VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id, category, day_date) DO UPDATE SET rating = excluded.rating
  `, [userId, category, rating, date])
}

const CAT_IN = `(${VALID_CATEGORIES.map(c => `'${c}'`).join(', ')})`

/** [{category, avg_rating, count}] */
export async function getRatings(userId, days = 1) {
  const dateFrom = addDays(await userToday(userId), -(days - 1))
  return all(`
    SELECT category, AVG(rating) as avg_rating, COUNT(*) as count FROM ratings
    WHERE user_id = ? AND day_date >= ? AND category IN ${CAT_IN}
    GROUP BY category
  `, [userId, dateFrom])
}

/** [{day_date, category, rating}] */
export async function getDailyRatings(userId, days = 7) {
  const dateFrom = addDays(await userToday(userId), -(days - 1))
  return all(`
    SELECT day_date, category, rating FROM ratings
    WHERE user_id = ? AND day_date >= ? AND category IN ${CAT_IN}
    ORDER BY day_date, category
  `, [userId, dateFrom])
}

async function ratingsOn(userId, day) {
  const rows = await all('SELECT category, rating FROM ratings WHERE user_id = ? AND day_date = ?', [userId, day])
  const out = {}
  for (const r of rows) out[r.category] = r.rating
  return out
}

export async function getTodayRatings(userId) {
  return ratingsOn(userId, await userToday(userId))
}

export async function getYesterdayRatings(userId) {
  return ratingsOn(userId, addDays(await userToday(userId), -1))
}

export async function checkAllCategoriesCompleted(userId) {
  const r = await getTodayRatings(userId)
  return VALID_CATEGORIES.every(c => c in r)
}

/** Only the three categories the user fills in by hand. */
export async function manualCategoriesCompleted(userId) {
  const r = await getTodayRatings(userId)
  return ['сон', 'зависание', 'настрой'].every(c => c in r)
}

// ---- ranks & sparks ----

export async function getOrCreateRankData(userId) {
  const row = await one('SELECT * FROM user_ranks WHERE user_id = ?', [userId])
  const today = await userToday(userId)
  if (row) {
    let { total_sparks, current_rank, last_spark_date, sparks_today,
      categories_completed_today: cat, workout_completed_today: wk } = row
    if (last_spark_date !== today) {
      sparks_today = 0; cat = 0; wk = 0
      await execute(`
        UPDATE user_ranks SET sparks_today = 0, categories_completed_today = 0,
          workout_completed_today = 0, last_spark_date = ? WHERE user_id = ?
      `, [today, userId])
    }
    const actual = getCurrentRank(total_sparks)
    if (actual !== current_rank) {
      current_rank = actual
      await execute('UPDATE user_ranks SET current_rank = ? WHERE user_id = ?', [current_rank, userId])
    }
    return {
      user_id: userId, total_sparks, current_rank, sparks_today,
      categories_completed_today: cat, workout_completed_today: wk,
    }
  }
  await execute(`
    INSERT INTO user_ranks (user_id, total_sparks, current_rank, last_spark_date, sparks_today,
      categories_completed_today, workout_completed_today) VALUES (?, 0, 1, ?, 0, 0, 0)
  `, [userId, today])
  return { user_id: userId, total_sparks: 0, current_rank: 1, sparks_today: 0, categories_completed_today: 0, workout_completed_today: 0 }
}

export async function deductSparkForSkip(userId) {
  const row = await one('SELECT total_sparks, current_rank FROM user_ranks WHERE user_id = ?', [userId])
  if (!row) return
  const total = Math.max(0, row.total_sparks - 1)
  await execute('UPDATE user_ranks SET total_sparks = ?, current_rank = ? WHERE user_id = ?', [total, getCurrentRank(total), userId])
}

/** → [success, sparksToday, rankUp, oldRank, newRank] */
export async function addSpark(userId, sparkType) {
  const data = await getOrCreateRankData(userId)
  const no = [false, data.sparks_today, false, data.current_rank, data.current_rank]
  if (sparkType !== 'bonus_high' && data.sparks_today >= MAX_SPARKS_PER_DAY) return no
  if (sparkType === 'categories' && data.categories_completed_today) return no
  if (sparkType === 'workout' && data.workout_completed_today) return no
  const oldRank = data.current_rank
  const today = await userToday(userId)
  if (sparkType === 'categories') {
    await execute(`
      UPDATE user_ranks SET total_sparks = total_sparks + ?, sparks_today = sparks_today + ?,
        categories_completed_today = 1, last_spark_date = ? WHERE user_id = ?
    `, [SPARK_FOR_CATEGORIES, SPARK_FOR_CATEGORIES, today, userId])
  } else {
    await execute(`
      UPDATE user_ranks SET total_sparks = total_sparks + ?, sparks_today = sparks_today + ?,
        workout_completed_today = 1, last_spark_date = ? WHERE user_id = ?
    `, [SPARK_FOR_WORKOUT, SPARK_FOR_WORKOUT, today, userId])
  }
  const n = await getOrCreateRankData(userId)
  return [true, n.sparks_today, n.current_rank > oldRank, oldRank, n.current_rank]
}

// ---- workouts counter ----

export async function getOrCreateWorkoutData(userId) {
  const row = await one('SELECT * FROM workouts WHERE user_id = ?', [userId])
  const today = await userToday(userId)
  const month = today.slice(0, 7)
  if (row) {
    let { monthly_goal: goal, current_count: count, last_workout_date: last, today_count: todayCount } = row
    if (last && last.slice(0, 7) !== month) {
      count = 0; todayCount = 0
      await execute('UPDATE workouts SET current_count = 0, today_count = 0, last_workout_date = ? WHERE user_id = ?', [today, userId])
    }
    if (last !== today) {
      todayCount = 0
      await execute('UPDATE workouts SET today_count = 0 WHERE user_id = ?', [userId])
    }
    return {
      user_id: userId,
      monthly_goal: await getMonthlyWorkoutGoal(userId, goal),
      current_count: count,
      last_workout_date: last,
      today_count: todayCount,
    }
  }
  await execute(`
    INSERT INTO workouts (user_id, monthly_goal, current_count, last_workout_date, today_count)
    VALUES (?, 0, 0, ?, 0)
  `, [userId, today])
  return { user_id: userId, monthly_goal: await getMonthlyWorkoutGoal(userId, 0), current_count: 0, last_workout_date: today, today_count: 0 }
}

function planStart(planData, fallback) {
  const s = (planData || {}).start_date
  return isDateStr(s) ? s : fallback
}

function cycleWeeksOf(planData) {
  const plan = (planData || {}).plan || {}
  return planData.cycle_weeks ?? plan.cycle_weeks ?? 1
}

/** Are there exercises in the plan on date d (weeks counted from the plan's start)? */
export function isPlannedTrainingDay(planData, d, start) {
  const plan = (planData || {}).plan || {}
  if (typeof plan !== 'object' || Array.isArray(plan) || d < start) return false
  const cycle = cycleWeeksOf(planData) || 1
  const weekIdx = (Math.max(0, Math.floor(daysBetween(start, d) / 7)) % cycle) + 1
  const week = plan[`week_${weekIdx}`] || plan.week_1 || {}
  const ex = week && typeof week === 'object' ? week[WEEKDAY_KEY[weekdayOf(d)]] : null
  return Array.isArray(ex) && ex.length > 0
}

export function countPlannedDays(planData, first, last) {
  const start = planStart(planData, first)
  let n = 0
  for (let d = first; d <= last; d = addDays(d, 1)) if (isPlannedTrainingDay(planData, d, start)) n++
  return n
}

export function countPlannedDaysInMonth(planData, year, month) {
  return countPlannedDays(planData, ymd(year, month, 1), ymd(year, month, daysInMonth(year, month)))
}

/** Monthly goal = planned training days; the old manual goal is the fallback. */
export async function getMonthlyWorkoutGoal(userId, storedGoal = 0) {
  try {
    const planData = await getAiPlan(userId)
    if (planData) {
      const now = await userNow(userId)
      const planned = countPlannedDaysInMonth(planData, now.year, now.month)
      if (planned > 0) return planned
    }
  } catch (e) {
    console.warn(`[WORKOUT GOAL] user=${userId}: ${e.message}`)
  }
  return storedGoal || 0
}

export async function setWorkoutGoal(userId, goal) {
  await execute(`
    INSERT INTO workouts (user_id, monthly_goal, current_count, last_workout_date, today_count)
    VALUES (?, ?, 0, ?, 0) ON CONFLICT(user_id) DO UPDATE SET monthly_goal = excluded.monthly_goal
  `, [userId, goal, await userToday(userId)])
}

export async function addWorkout(userId) {
  const today = await userToday(userId)
  await execute(`
    UPDATE workouts SET current_count = current_count + 1, today_count = today_count + 1,
      last_workout_date = ? WHERE user_id = ?
  `, [today, userId])
  return getOrCreateWorkoutData(userId)
}

export async function changeWorkoutGoal(userId, goal) {
  await execute('UPDATE workouts SET monthly_goal = ? WHERE user_id = ?', [goal, userId])
}

// ---- diet ----

export async function saveDietProfile(userId, p) {
  const today = await userToday(userId)
  await execute(`
    INSERT INTO diet_profile (user_id, weight, height, age, gender, activity_level,
      goal_type, target_weight_change, target_days, daily_calories, last_update_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
      weight = excluded.weight, height = excluded.height, age = excluded.age,
      gender = excluded.gender, activity_level = excluded.activity_level,
      goal_type = excluded.goal_type, target_weight_change = excluded.target_weight_change,
      target_days = excluded.target_days, daily_calories = excluded.daily_calories,
      last_update_date = excluded.last_update_date
  `, [userId, p.weight, p.height, p.age, p.gender, p.activity_level, p.goal_type,
    p.target_weight_change, p.target_days, p.daily_calories, today])
}

export async function getDietProfile(userId) {
  return one('SELECT * FROM diet_profile WHERE user_id = ?', [userId])
}

export async function saveFoodLog(userId, mealType, description, calories, protein = null, fat = null, carbs = null) {
  const today = await userToday(userId)
  await execute(`
    INSERT INTO diet_log (user_id, date, meal_type, food_description, calories, protein, fat, carbs)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `, [userId, today, mealType, description, calories, protein, fat, carbs])
}

export async function getTodayCalories(userId) {
  const row = await one('SELECT SUM(calories) AS s FROM diet_log WHERE user_id = ? AND date = ?', [userId, await userToday(userId)])
  return (row && row.s) || 0.0
}

export async function getTodayMacros(userId) {
  const row = await one('SELECT SUM(protein) AS p, SUM(fat) AS f, SUM(carbs) AS c FROM diet_log WHERE user_id = ? AND date = ?',
    [userId, await userToday(userId)])
  return { protein: row.p || 0.0, fat: row.f || 0.0, carbs: row.c || 0.0 }
}

/** [{meal_type, food_description, calories, protein, fat, carbs}] */
export async function getTodayFoodLog(userId) {
  return all(`
    SELECT meal_type, food_description, calories, protein, fat, carbs FROM diet_log
    WHERE user_id = ? AND date = ? ORDER BY timestamp
  `, [userId, await userToday(userId)])
}

/** Previously logged dishes, newest first, de-duplicated by name (case-insensitive). */
export async function getFoodHistory(userId, limit = 300) {
  const rows = await all(`
    SELECT food_description, calories, protein, fat, carbs FROM diet_log
    WHERE user_id = ? ORDER BY id DESC LIMIT 2000
  `, [userId])
  const seen = new Set(), foods = []
  for (const r of rows) {
    const key = (r.food_description || '').trim().toLowerCase()
    if (!key || seen.has(key)) continue
    seen.add(key)
    foods.push({ description: r.food_description.trim(), calories: r.calories, protein: r.protein, fat: r.fat, carbs: r.carbs })
    if (foods.length >= limit) break
  }
  return foods
}

export async function saveWeightLog(userId, weight) {
  await execute('INSERT INTO weight_log (user_id, date, weight) VALUES (?, ?, ?)', [userId, await userToday(userId), weight])
}

export async function getLastWeight(userId) {
  const row = await one('SELECT weight FROM weight_log WHERE user_id = ? ORDER BY date DESC LIMIT 1', [userId])
  return row ? row.weight : null
}

export async function saveBodyFat(userId, bodyFat) {
  await execute('INSERT INTO body_fat_log (user_id, date, body_fat) VALUES (?, ?, ?)', [userId, await userToday(userId), bodyFat])
}

export async function saveBodyScore(userId, result) {
  const today = await userToday(userId)
  await execute(`
    INSERT INTO body_scores (user_id, date, score, summary, strengths, weaknesses) VALUES (?, ?, ?, ?, ?, ?)
  `, [userId, today, Math.trunc(result.score), result.summary || '',
    pyJson(result.strengths || []), pyJson(result.weaknesses || [])])
  return { ...result, date: today }
}

function jsonList(raw) {
  try {
    const v = JSON.parse(raw || '[]')
    return Array.isArray(v) ? v : []
  } catch { return [] }
}

export async function getLastBodyScore(userId) {
  const row = await one(`
    SELECT date, score, summary, strengths, weaknesses FROM body_scores
    WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 1
  `, [userId])
  if (!row) return null
  return { date: row.date, score: row.score, summary: row.summary || '', strengths: jsonList(row.strengths), weaknesses: jsonList(row.weaknesses) }
}

/** [[date, score]] ascending; the last photo of a day wins. */
export async function getBodyScoreHistory(userId) {
  const rows = await all('SELECT date, score FROM body_scores WHERE user_id = ? ORDER BY date, id', [userId])
  const byDate = new Map()
  for (const r of rows) byDate.set(r.date, r.score)
  return [...byDate.entries()].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
}

/** Map "kind|start|end|signature" → {what, fix} */
export async function getPotentialNotes(userId) {
  const rows = await all('SELECT kind, start_date, end_date, signature, what, fix FROM potential_notes WHERE user_id = ?', [userId])
  const out = new Map()
  for (const r of rows) out.set([r.kind, r.start_date, r.end_date, r.signature].join('|'), { what: r.what, fix: r.fix })
  return out
}

export async function savePotentialNote(userId, kind, start, end, signature, what, fix) {
  await execute(`
    INSERT INTO potential_notes (user_id, kind, start_date, end_date, signature, what, fix)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id, kind, start_date, end_date, signature) DO UPDATE SET what = excluded.what, fix = excluded.fix
  `, [userId, kind, start, end, signature, what, fix])
}

export async function addMyFood(userId, name, calories, protein = null, fat = null, carbs = null) {
  try {
    await execute('INSERT INTO my_foods (user_id, name, calories, protein, fat, carbs) VALUES (?, ?, ?, ?, ?, ?)',
      [userId, name, calories, protein, fat, carbs])
  } catch (e) {
    if (!isUniqueViolation(e)) throw e
  }
}

/** [{name, calories}] */
export async function getMyFoods(userId) {
  return all('SELECT name, calories FROM my_foods WHERE user_id = ? ORDER BY name', [userId])
}

export async function saveLastAiAnswer(userId, answer) {
  await execute('UPDATE user_settings SET last_ai_answer = ? WHERE user_id = ?', [answer, userId])
}

export async function getLastAiAnswer(userId) {
  const row = await one('SELECT last_ai_answer FROM user_settings WHERE user_id = ?', [userId])
  return row ? row.last_ai_answer : null
}

export function calculateBmr(weight, height, age, gender) {
  if (gender === 'мужской') return 10 * weight + 6.25 * height - 5 * age + 5
  return 10 * weight + 6.25 * height - 5 * age - 161
}

export const calculateTdee = (bmr, activity) => bmr * activity

/** → [calories, warning] */
export function calculateDailyCalories(tdee, goalType, targetWeightChange, targetDays, gender) {
  if (goalType === 'maintain') return [tdee, 'ok']
  if (!targetDays || targetDays <= 0) return [tdee, 'ok']
  let adj = Math.abs(targetWeightChange) * 7700 / targetDays
  const maxAdj = 1000
  let warning = 'ok'
  if (adj > maxAdj) {
    adj = maxAdj
    warning = `⚠️ Цель слишком амбициозна. Дефицит ограничен ${maxAdj} ккал/день. Для достижения цели потребуется больше времени.`
  }
  let calories = goalType === 'loss' ? tdee - adj : tdee + adj
  const minCal = gender === 'женский' ? 1200 : 1500
  if (calories < minCal) {
    calories = minCal
    warning = `⚠️ Рассчитанная норма слишком низкая. Установлен безопасный минимум ${minCal} ккал/день. Рекомендуется пересмотреть цель.`
  }
  return [calories, warning]
}

const PROTEIN_PER_KG = { loss: 2.0, gain: 1.8, maintain: 1.6 }

export function calculateMacroGoals(dailyCalories, weight, goalType) {
  if (!dailyCalories || dailyCalories <= 0) return { protein: 0.0, fat: 0.0, carbs: 0.0 }
  let protein = (weight || 0) * (PROTEIN_PER_KG[goalType || 'maintain'] ?? 1.6)
  if (protein <= 0) protein = dailyCalories * 0.25 / 4
  protein = Math.min(protein, dailyCalories * 0.35 / 4)
  const fat = dailyCalories * 0.25 / 9
  const carbs = Math.max(0.0, (dailyCalories - protein * 4 - fat * 9) / 4)
  return { protein: pyRound(protein), fat: pyRound(fat), carbs: pyRound(carbs) }
}

export async function getMacroGoals(userId, profile) {
  if (!profile) return { protein: 0.0, fat: 0.0, carbs: 0.0 }
  const weight = (await getLastWeight(userId)) || profile.weight
  return calculateMacroGoals(profile.daily_calories || 0, weight, profile.goal_type)
}

// ---- tasks ----

function taskRow(r, isDone) {
  return {
    id: r.id, title: r.title, is_priority: !!r.is_priority, deadline: r.deadline,
    repeat_days: r.repeat_days, is_done: isDone, done_date: r.done_date,
  }
}

export async function getTasksForToday(userId) {
  const now = await userNow(userId)
  const wd = String(now.weekday)
  const rows = await all(`
    SELECT id, title, is_priority, deadline, repeat_days, is_done, done_date FROM tasks WHERE user_id = ?
  `, [userId])
  const out = []
  for (const r of rows) {
    if (r.repeat_days) {
      if (!r.repeat_days.split(',').includes(wd)) continue
      if (r.done_date === now.date) continue
    } else if (r.is_done) continue
    out.push(taskRow(r, !!r.is_done))
  }
  return out
}

export async function getAllActiveTasks(userId) {
  const today = await userToday(userId)
  const rows = await all(`
    SELECT id, title, is_priority, deadline, repeat_days, is_done, done_date FROM tasks
    WHERE user_id = ? ORDER BY is_priority DESC, deadline ASC NULLS LAST, id ASC
  `, [userId])
  const out = []
  for (const r of rows) {
    if (r.repeat_days) out.push(taskRow(r, r.done_date === today))
    else if (!r.is_done) out.push(taskRow(r, false))
  }
  return out
}

/** Main-menu tasks: priority ones + deadline within 3 days. */
export async function getUrgentTasksForMenu(userId) {
  const today = await userToday(userId)
  const urgent = []
  for (const t of await getTasksForToday(userId)) {
    let daysLeft = null
    if (t.deadline && isDateStr(t.deadline)) daysLeft = daysBetween(today, t.deadline)
    if (t.is_priority || (daysLeft !== null && daysLeft <= 3)) {
      t.days_left = daysLeft
      urgent.push(t)
    }
  }
  return urgent.slice(0, 5)
}

export async function completeTask(taskId, userId) {
  const today = await userToday(userId)
  const row = await one('SELECT repeat_days FROM tasks WHERE id = ? AND user_id = ?', [taskId, userId])
  if (!row) return
  if (row.repeat_days) await execute('UPDATE tasks SET done_date = ? WHERE id = ? AND user_id = ?', [today, taskId, userId])
  else await execute('UPDATE tasks SET is_done = 1, done_date = ? WHERE id = ? AND user_id = ?', [today, taskId, userId])
}

export async function deleteTask(taskId, userId) {
  await execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', [taskId, userId])
}

export async function addTask(userId, title, isPriority, deadline, repeatDays) {
  await execute('INSERT INTO tasks (user_id, title, is_priority, deadline, repeat_days) VALUES (?, ?, ?, ?, ?)',
    [userId, title, isPriority ? 1 : 0, deadline ?? null, repeatDays ?? null])
}

// ---- AI workout plan & sessions ----

export async function getAiPlan(userId) {
  const row = await one('SELECT * FROM ai_workout_plan WHERE user_id = ?', [userId])
  if (!row) return null
  return { ...row, plan: JSON.parse(row.plan_json) }
}

export async function saveAiPlan(userId, mode, goal, level, daysPerWeek, plan, cycleWeeks = 1) {
  const today = await userToday(userId)
  await execute(`
    INSERT INTO ai_workout_plan (user_id, mode, goal, level, days_per_week, plan_json, cycle_weeks, start_date, last_monthly_review)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
      mode=excluded.mode, goal=excluded.goal, level=excluded.level,
      days_per_week=excluded.days_per_week, plan_json=excluded.plan_json,
      cycle_weeks=excluded.cycle_weeks,
      start_date=CASE WHEN ai_workout_plan.start_date IS NULL THEN excluded.start_date ELSE ai_workout_plan.start_date END
  `, [userId, mode, goal ?? null, level ?? null, daysPerWeek ?? null, pyJson(plan), cycleWeeks, today, today])
}

export async function deleteAllWorkoutData(userId) {
  for (const t of ['ai_workout_plan', 'ai_workout_sessions', 'ai_exercise_logs', 'exercise_substitutions',
    'workout_log', 'exercises', 'exercise_categories']) {
    await execute(`DELETE FROM ${t} WHERE user_id = ?`, [userId])
  }
  await execute('UPDATE workouts SET current_count=0, today_count=0, last_workout_date=NULL WHERE user_id = ?', [userId])
}

/** Which week of the cycle applies today: 'week_N'. */
export function currentWeekKey(planData, startDate, today) {
  const start = isDateStr(startDate) ? startDate : today
  const weeksPassed = Math.max(0, Math.floor(daysBetween(start, today) / 7))
  const plan = planData.plan || planData
  const cycle = planData.cycle_weeks ?? plan.cycle_weeks ?? 1
  return `week_${(weeksPassed % (cycle || 1)) + 1}`
}

export async function getCurrentWeekSessionKey(planData, startDate, userId) {
  return currentWeekKey(planData, startDate, await userToday(userId))
}

/** Today's exercises (user's time) or null on a rest day. */
export async function getTodayPlan(planData, userId) {
  if (!planData || !planData.plan) return null
  const now = await userNow(userId)
  const startDate = planData.start_date || now.date
  const weekKey = currentWeekKey(planData, startDate, now.date)
  const week = planData.plan[weekKey] || planData.plan.week_1 || {}
  const ex = week[WEEKDAY_KEY[now.weekday]]
  if (!Array.isArray(ex) || !ex.length) return null
  return ex
}

function sessionRow(row) {
  return row ? { ...row, plan: JSON.parse(row.plan_json) } : null
}

export async function getTodaySession(userId) {
  const row = await one('SELECT * FROM ai_workout_sessions WHERE user_id = ? AND date = ? ORDER BY id ASC LIMIT 1',
    [userId, await userToday(userId)])
  return sessionRow(row)
}

export async function getSessionById(userId, sessionId) {
  return sessionRow(await one('SELECT * FROM ai_workout_sessions WHERE id = ? AND user_id = ?', [sessionId, userId]))
}

export async function createTodaySession(userId, planData) {
  const existing = await getTodaySession(userId)
  if (existing) return existing
  const exercises = await getTodayPlan(planData, userId)
  if (!exercises) return null
  const now = await userNow(userId)
  const weekKey = currentWeekKey(planData, planData.start_date || now.date, now.date)
  const sessionKey = `${weekKey}_${WEEKDAY_KEY[now.weekday]}`
  try {
    // Plain INSERT: the unique index on (user_id, date) settles races.
    await execute(`
      INSERT INTO ai_workout_sessions (user_id, date, weekday, session_key, plan_json, status)
      VALUES (?, ?, ?, ?, ?, 'pending')
    `, [userId, now.date, now.weekday, sessionKey, pyJson(exercises)])
  } catch (e) {
    if (!isUniqueViolation(e)) console.warn('[SESSION] Insert error:', e.message)
  }
  return getTodaySession(userId)
}

export async function getSessionExerciseLogs(sessionId) {
  const rows = await all('SELECT * FROM ai_exercise_logs WHERE session_id = ? ORDER BY id', [sessionId])
  return rows.map(r => {
    const d = { ...r }
    if (d.planned_json) d.planned = JSON.parse(d.planned_json)
    if (d.result_json) d.result = JSON.parse(d.result_json)
    return d
  })
}

/** Up to 3 previous done sessions of the same day type, newest first. */
export async function getPreviousSameSession(userId, sessionKey, excludeDate) {
  const parts = sessionKey.split('_')
  const tail = parts.length > 2 ? parts.slice(2).join('_') : parts[parts.length - 1]
  const rows = await all(`
    SELECT * FROM ai_workout_sessions
    WHERE user_id = ? AND session_key LIKE ? AND date != ? AND status = 'done'
    ORDER BY date DESC LIMIT 3
  `, [userId, `%${tail}`, excludeDate])
  if (!rows.length) return null
  const out = []
  for (const r of rows) {
    const s = sessionRow(r)
    s.logs = await getSessionExerciseLogs(s.id)
    out.push(s)
  }
  return out
}

export async function updatePlanJson(userId, plan) {
  await execute('UPDATE ai_workout_plan SET plan_json = ? WHERE user_id = ?', [pyJson(plan), userId])
}

/** Update a session's exercises and the same day in the main plan. */
export async function updateSessionExercisePlan(userId, sessionId, sessionKey, exercises) {
  await execute('UPDATE ai_workout_sessions SET plan_json = ? WHERE id = ?', [pyJson(exercises), sessionId])
  const planData = await getAiPlan(userId)
  if (planData) {
    const plan = planData.plan
    const parts = sessionKey.split('_')
    if (parts.length >= 3) {
      const weekKey = `${parts[0]}_${parts[1]}`
      const dayKey = parts.slice(2).join('_')
      if (plan[weekKey] && dayKey in plan[weekKey]) {
        plan[weekKey][dayKey] = exercises
        await updatePlanJson(userId, plan)
      }
    }
  }
}

/** Off-schedule session today (rest day). null when today already has one. */
export async function createExtraSession(userId, sessionKey, exercises, status = 'pending') {
  const now = await userNow(userId)
  try {
    await execute(`
      INSERT INTO ai_workout_sessions (user_id, date, weekday, session_key, plan_json, status, completed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `, [userId, now.date, now.weekday, sessionKey, pyJson(exercises), status, status === 'done' ? now.date : null])
  } catch (e) {
    if (!isUniqueViolation(e)) console.warn('[SESSION] Extra insert error:', e.message)
    return null
  }
  return getTodaySession(userId)
}

export async function deleteSession(userId, sessionId) {
  await execute('DELETE FROM ai_exercise_logs WHERE session_id = ? AND user_id = ?', [sessionId, userId])
  await execute('DELETE FROM ai_workout_sessions WHERE id = ? AND user_id = ?', [sessionId, userId])
}

export async function addExerciseSubstitution(userId, originalName, substituteName, sets, reps, weight) {
  const r = await execute(`
    INSERT INTO exercise_substitutions (user_id, original_name, substitute_name, sets, reps, weight)
    VALUES (?, ?, ?, ?, ?, ?)
  `, [userId, originalName, substituteName, sets ?? null, reps == null ? null : String(reps), weight ?? null])
  return r.lastInsertRowid
}

/** Latest distinct substitutes for an exercise (newest first). */
export async function getExerciseSubstitutions(userId, originalName, limit = 3) {
  const rows = await all('SELECT * FROM exercise_substitutions WHERE user_id = ? ORDER BY id DESC LIMIT 1000', [userId])
  const original = originalName.trim().toLowerCase()
  const seen = new Set(), out = []
  for (const d of rows) {
    if (d.original_name.trim().toLowerCase() !== original) continue
    const key = d.substitute_name.trim().toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(d)
    if (out.length >= limit) break
  }
  return out
}

export async function getExerciseSubstitution(userId, subId) {
  return one('SELECT * FROM exercise_substitutions WHERE id = ? AND user_id = ?', [subId, userId])
}

export async function setSubstitutionWeight(userId, subId, weight) {
  await execute('UPDATE exercise_substitutions SET weight = ? WHERE id = ? AND user_id = ?', [weight, subId, userId])
}

/** → [ddmm, weekdayName] of the next training day, or [null, null]. */
export async function getNextTrainingDay(planData, userId) {
  const plan = planData.plan
  const today = await userToday(userId)
  const start = isDateStr(planData.start_date) ? planData.start_date : today
  for (let off = 1; off < 8; off++) {
    const d = addDays(today, off)
    const wd = weekdayOf(d)
    const cycle = planData.cycle_weeks || 1
    const weekKey = `week_${(Math.floor(daysBetween(start, d) / 7) % cycle + cycle) % cycle + 1}`
    const week = plan[weekKey] || plan.week_1 || {}
    const ex = week[WEEKDAY_KEY[wd]]
    if (ex && (!Array.isArray(ex) || ex.length)) return [ddmm(d), WEEKDAY_RU[wd]]
  }
  return [null, null]
}

/** → [done this week, planned this week] */
export async function getWeeklyWorkoutProgress(userId) {
  const planData = await getAiPlan(userId)
  const today = await userToday(userId)
  const ws = weekStart(today)
  let perWeek = 0
  if (planData) perWeek = countPlannedDays(planData, ws, addDays(ws, 6)) || planData.days_per_week || 0
  const row = await one("SELECT COUNT(*) AS n FROM ai_workout_sessions WHERE user_id = ? AND date >= ? AND status = 'done'", [userId, ws])
  return [row ? row.n : 0, perWeek]
}
