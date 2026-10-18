// trackcheck/services/tracker_service.py — automatic «еда» and «активность»
// ratings. The 00:01 / 23:55 scheduled passes stay in Python on the worker;
// this module is what the handlers call after logging food or a workout.

import * as repo from './repo.js'
import { userNow, userToday } from './dates.js'
import { pyRound } from './util.js'

export const AUTO_CATEGORIES = ['еда', 'активность']

const DEVIATION_SCALE = [
  [0.05, 10], [0.10, 9], [0.15, 8], [0.20, 7], [0.25, 6],
  [0.30, 5], [0.40, 4], [0.50, 3], [0.65, 2],
]

const EATING_CURVE = [[0, 0.0], [6, 0.0], [9, 0.25], [13, 0.55], [19, 0.85], [22, 1.0], [24, 1.0]]

function scoreFromDeviation(dev) {
  dev = pyRound(dev, 6)
  for (const [limit, score] of DEVIATION_SCALE) if (dev <= limit) return score
  return 1
}

function expectedFraction(h) {
  for (let i = 0; i + 1 < EATING_CURVE.length; i++) {
    const [h0, f0] = EATING_CURVE[i], [h1, f1] = EATING_CURVE[i + 1]
    if (h0 <= h && h <= h1) return f0 + (f1 - f0) * (h - h0) / (h1 - h0)
  }
  return 1.0
}

/** hourFloat = null → end-of-day score; otherwise adjusted for the time of day. */
export function dietScore(eaten, goal, hourFloat = null) {
  if (eaten <= 0 || goal <= 0) return 1
  if (eaten > goal) return scoreFromDeviation(eaten / goal - 1)
  const target = hourFloat === null ? goal : goal * expectedFraction(hourFloat)
  if (target <= 0 || eaten >= target) return hourFloat !== null ? 10 : scoreFromDeviation(1 - eaten / goal)
  return scoreFromDeviation(1 - eaten / target)
}

function num(v) {
  if (typeof v === 'boolean' || v === null || v === undefined) return null
  if (typeof v === 'number') return v > 0 ? v : null
  const m = /\d+(?:[.,]\d+)?/.exec(String(v))
  if (!m) return null
  const x = parseFloat(m[0].replace(',', '.'))
  return x > 0 ? x : null
}

export function exerciseScore(planned, log) {
  if (!log || log.status !== 'done') return 0.0
  const result = log.result || {}
  const parts = []
  for (const [pk, dk] of [['sets', 'sets_done'], ['reps', 'reps_done'], ['weight', 'weight_done']]) {
    const p = num((planned || {})[pk]), d = num(result[dk])
    if (p !== null && d !== null) parts.push(Math.min(1.0, d / p))
    else if (p !== null && (result[dk] === 0 || result[dk] === '0')) parts.push(0.0)
  }
  return parts.length ? parts.reduce((a, b) => a + b, 0) / parts.length : 1.0
}

export function workoutScore(planned, logs) {
  const name = (ex) => (ex.exercise || ex.name || '').trim()
  const byName = new Map()
  for (const l of logs) {
    const k = (l.exercise_name || '').trim()
    if (!byName.has(k)) byName.set(k, l)
  }
  const items = (planned && planned.length) ? planned : logs.map(l => l.planned || { exercise: l.exercise_name })
  if (!items.length) return 1
  const total = items.reduce((s, ex) => s + exerciseScore(ex, byName.get(name(ex))), 0) / items.length
  return Math.max(1, Math.min(10, Math.trunc(1 + 9 * total + 0.5)))
}

async function hourFloat(userId) {
  const now = await userNow(userId)
  return now.hour + now.minute / 60
}

export async function computeDietRating(userId, final) {
  const profile = await repo.getDietProfile(userId)
  const goal = profile ? Number(profile.daily_calories || 0) : 0
  const eaten = Number((await repo.getTodayCalories(userId)) || 0)
  if (!final && (goal <= 0 || eaten <= 0)) return null
  return dietScore(eaten, goal, final ? null : await hourFloat(userId))
}

export async function computeActivityRating(userId, final) {
  const planData = await repo.getAiPlan(userId)
  if (!planData) return final ? 1 : null
  const session = await repo.getTodaySession(userId)
  if (session && session.status === 'skipped') return 1
  const todayPlan = await repo.getTodayPlan(planData, userId)
  if (!todayPlan && !session) return 5
  if (!session) return final ? 1 : null
  if (session.status !== 'done' && !final) return null
  const planned = Array.isArray(session.plan) ? session.plan : (todayPlan || [])
  return workoutScore(planned, await repo.getSessionExerciseLogs(session.id))
}

async function saveAuto(userId, category, score) {
  if (score === null || score === undefined) return false
  await repo.saveRating(userId, category, Math.trunc(score), await userToday(userId))
  if (await repo.checkAllCategoriesCompleted(userId)) {
    const [ok] = await repo.addSpark(userId, 'categories')
    return !!ok
  }
  return false
}

export async function syncDietRatingForToday(userId) {
  await saveAuto(userId, 'еда', await computeDietRating(userId, false))
}

export async function syncActivityRatingForToday(userId) {
  await saveAuto(userId, 'активность', await computeActivityRating(userId, false))
}

export async function ensureRestDayRating(userId) {
  if ('активность' in (await repo.getTodayRatings(userId))) return
  const planData = await repo.getAiPlan(userId)
  if (!planData || (await repo.getTodaySession(userId)) || (await repo.getTodayPlan(planData, userId))) return
  await saveAuto(userId, 'активность', 5)
}
