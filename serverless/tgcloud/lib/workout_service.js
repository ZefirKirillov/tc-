// trackcheck/services/workout_service.py

import { execute, all } from './turso.js'
import { WEEKDAY_KEY, WEEKDAY_RU } from './config.js'
import { ddmmyyyy, userToday } from './dates.js'
import { pyRound, pyVal, pyJson } from './util.js'
import * as repo from './repo.js'

/** Python dict.get(key, default): the default only when the key is missing. */
export const pget = (o, k, d) => (o && Object.prototype.hasOwnProperty.call(o, k) ? o[k] : d)
/** …and as an f-string shows it (None for null). */
export const pshow = (o, k, d) => pyVal(pget(o, k, d))

export const exerciseName = (ex) => pget(ex, 'exercise', pget(ex, 'name', '?'))

export function formatPlanForDisplay(exercises, prevLogs = null) {
  const lines = exercises.map((ex, i) => {
    let line = `${i + 1}. ${pyVal(exerciseName(ex))}  ${pshow(ex, 'sets', '?')}×${pshow(ex, 'reps', '?')}`
    if (ex.weight) line += ` @ ${ex.weight}кг`
    return line
  })
  let text = lines.join('\n')
  if (prevLogs && prevLogs.length) {
    const important = []
    for (const log of prevLogs) {
      if (log.status === 'skipped') important.push(`⏭ ${log.exercise_name} — пропущено`)
      else if (log.result && log.result.note) important.push(`⚠️ ${log.exercise_name} — ${log.result.note}`)
    }
    if (important.length) text += '\n\nПрошлый раз:\n' + important.join('\n')
  }
  return text
}

export function formatExerciseCard(exercise, index, total, prevResult = null) {
  let text = `Упражнение ${index} из ${total}\n\n`
  text += `${pyVal(exerciseName(exercise))}\n`
  text += `Цель: ${pshow(exercise, 'sets', '?')} подхода × ${pshow(exercise, 'reps', '?')} повторений`
  if (exercise.weight) text += ` @ ${exercise.weight} кг`
  if (prevResult && Object.keys(prevResult).length) {
    text += '\n\nПрошлый раз: '
    if (prevResult.sets_done) text += `${prevResult.sets_done}×${pshow(prevResult, 'reps_done', '?')}`
    if (prevResult.weight_done) text += ` @ ${prevResult.weight_done} кг`
    if (prevResult.note) text += ` (${prevResult.note})`
  }
  return text + '\n\nНапиши что сделал или нажми кнопку:'
}

export function applyMonthlyChanges(planData, acceptedIndices, changes) {
  const plan = structuredCloneish(planData.plan)
  for (const i of acceptedIndices) {
    if (i >= changes.length) continue
    const ch = changes[i]
    const week = plan[ch.week] || {}
    for (const ex of week[ch.day] || []) {
      if (ex.exercise === ch.old_exercise) ex.exercise = ch.new_exercise
    }
  }
  return plan
}

export const structuredCloneish = (o) => JSON.parse(JSON.stringify(o))

const numbers = (v) => (String(v ?? 'None').match(/\d+(?:[.,]\d+)?/g) || []).map(n => parseFloat(n.replace(',', '.')))

/** Weight goal met: sets, reps and weight not below plan. */
export function goalMet(target, result) {
  if (!target.weight || !result || result.completed === false) return false
  const tSets = numbers(target.sets), tReps = numbers(target.reps), tWeight = numbers(target.weight)
  const dSets = numbers(result.sets_done), dReps = numbers(result.reps_done)
  let dWeight = numbers(result.weight_done)
  if (!dWeight.length) dWeight = tWeight
  if (!(tSets.length && tReps.length && tWeight.length && dSets.length && dReps.length && dWeight.length)) return false
  const dRepsVal = dReps.length > 1 ? Math.min(...dReps) : dReps[0]
  return dSets[0] >= tSets[0] && dRepsVal >= Math.max(...tReps) && dWeight[0] >= tWeight[0]
}

/** f"{float(w):g}" */
export const formatWeight = (w) => String(parseFloat(Number(w).toPrecision(6)))

export function raiseExerciseWeight(plan, name, increment) {
  plan = structuredCloneish(plan)
  const target = name.trim().toLowerCase()
  for (const [wk, week] of Object.entries(plan)) {
    if (!wk.startsWith('week_') || !week || typeof week !== 'object' || Array.isArray(week)) continue
    for (const day of Object.values(week)) {
      if (!Array.isArray(day)) continue
      for (const ex of day) {
        const n = String(exerciseName({ exercise: pget(ex, 'exercise', pget(ex, 'name', '')) })).trim().toLowerCase()
        const w = numbers(ex.weight)
        if (n === target && w.length) ex.weight = pyRound(w[0] + increment, 2)
      }
    }
  }
  return plan
}

const DAY_ORDER = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
const DAY_NAMES = { monday: 'Пн', tuesday: 'Вт', wednesday: 'Ср', thursday: 'Чт', friday: 'Пт', saturday: 'Сб', sunday: 'Вс' }

/** _format_full_plan */
export function formatFullPlan(plan, goal, level, days) {
  const lines = []
  if (goal) lines.push(`Твой план — ${goal}, ${level}\n`)
  let cycle = pget(plan, 'cycle_weeks', 1)
  if (!cycle || cycle < 1) cycle = 1
  for (let w = 1; w <= cycle; w++) {
    const week = plan[`week_${w}`] || {}
    if (!Object.keys(week).length) continue
    if (cycle > 1) lines.push(`Неделя ${w}:`)
    for (const dk of DAY_ORDER) {
      const exs = week[dk]
      if (!exs || !exs.length) continue
      lines.push(`\n${DAY_NAMES[dk]}:`)
      for (const ex of exs) {
        let line = `  ${pyVal(exerciseName(ex))}  ${pshow(ex, 'sets', '?')}×${pshow(ex, 'reps', '?')}`
        if (ex.weight) line += ` @ ${ex.weight}кг`
        lines.push(line)
      }
    }
  }
  return lines.join('\n')
}

/** _format_session_detail */
export async function formatSessionDetail(session) {
  const wd = WEEKDAY_RU[pget(session, 'weekday', 0)] || ''
  const lines = [`📅 ${wd}, ${ddmmyyyy(session.date)}`]
  if (session.status === 'skipped') {
    const reason = session.skip_reason || ''
    lines.push('⏭ Пропуск' + (reason ? ` — ${reason}` : ''))
    return lines.join('\n')
  }
  for (const log of await repo.getSessionExerciseLogs(session.id)) {
    const icon = log.status === 'done' ? '✅' : '⏭'
    const name = log.exercise_name
    const planned = log.planned || {}
    const res = log.result
    let planStr = `${pshow(planned, 'sets', '?')}×${pshow(planned, 'reps', '?')}`
    if (planned.weight) planStr += ` @ ${planned.weight}кг`
    if (res && typeof res === 'object' && log.status === 'done') {
      const w = res.weight_done
      let doneStr = `${pshow(res, 'sets_done', '?')}×${pshow(res, 'reps_done', '?')}` + (w ? ` @ ${w}кг` : '')
      if (res.note && !log.planned) doneStr += ` (${res.note})`
      if (res.replaced) lines.push(`🔄 ${name} (вместо «${res.replaced}»)\n   Факт: ${doneStr}`)
      else if (!log.planned) lines.push(`${icon} ${name}\n   Факт: ${doneStr}`)
      else lines.push(`${icon} ${name}\n   План: ${planStr} → Факт: ${doneStr}`)
    } else {
      lines.push(`${icon} ${name} — ${planStr}`)
    }
  }
  if (session.feedback) lines.push(`\n💬 ${session.feedback}`)
  return lines.join('\n')
}

export async function logExercise(sessionId, userId, name, planned, result, rawInput = null, status = 'done') {
  await execute(`
    INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, raw_input, result_json, status)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `, [sessionId, userId, name, planned == null ? null : pyJson(planned), rawInput,
    result == null ? null : pyJson(result), status])
}

/** Count a workout: counter, spark, streak → [sparkOk, rankUp, newRank] */
export async function countWorkout(userId) {
  await repo.addWorkout(userId)
  const [ok, , rankUp, , newRank] = await repo.addSpark(userId, 'workout')
  await repo.updateStreak(userId)
  return [ok, rankUp, newRank]
}

export function planRaiseTarget(ex, result = null) {
  if (ex.weight && (result === null || goalMet(ex, result))) return { kind: 'plan', name: exerciseName(ex), weight: ex.weight }
  return null
}

export async function applyWeightRaise(userId, target, increment) {
  const newWeight = pyRound(Number(target.weight) + increment, 2)
  if (target.kind === 'plan') {
    const planData = await repo.getAiPlan(userId)
    if (planData) await repo.updatePlanJson(userId, raiseExerciseWeight(planData.plan, target.name, increment))
  } else {
    await repo.setSubstitutionWeight(userId, Math.trunc(target.sub_id), newWeight)
  }
  return newWeight
}

export async function substitutionSuggestions(userId, originalName) {
  return (await repo.getExerciseSubstitutions(userId, originalName))
    .map(s => ({ id: s.id, name: s.substitute_name, sets: s.sets, reps: s.reps, weight: s.weight }))
}

/** Repeat a previous substitution with the same numbers → [result, raiseTarget] */
export async function logSubstitutionRepeat(userId, sessionId, ex, sub) {
  const original = exerciseName(ex)
  const result = { sets_done: sub.sets, reps_done: sub.reps, weight_done: sub.weight, completed: true, note: null, replaced: original }
  await logExercise(sessionId, userId, sub.substitute_name, ex, result)
  const newId = await repo.addExerciseSubstitution(userId, original, sub.substitute_name, sub.sets, sub.reps, sub.weight)
  const raise = sub.weight ? { kind: 'sub', sub_id: newId, name: sub.substitute_name, weight: sub.weight } : null
  return [result, raise]
}

/** A substitution described in text (already parsed) → [results, raiseTarget] */
export async function logSubstitutionItems(userId, sessionId, ex, items, raw) {
  const original = exerciseName(ex)
  const previous = new Map()
  for (const s of (await repo.getExerciseSubstitutions(userId, original, 100)).reverse()) {
    previous.set(s.substitute_name.trim().toLowerCase(), s)
  }
  const results = []
  let raise = null
  for (const it of items) {
    const result = { sets_done: it.sets_done ?? null, reps_done: it.reps_done ?? null, weight_done: it.weight_done ?? null,
      completed: true, note: it.note ?? null, replaced: original }
    await logExercise(sessionId, userId, it.exercise, ex, result, raw)
    const newId = await repo.addExerciseSubstitution(userId, original, it.exercise, it.sets_done, it.reps_done, it.weight_done)
    const prev = previous.get(it.exercise.trim().toLowerCase())
    if (raise === null && prev && goalMet({ sets: prev.sets, reps: prev.reps, weight: prev.weight }, result)) {
      raise = { kind: 'sub', sub_id: newId, name: it.exercise, weight: it.weight_done || prev.weight }
    }
    results.push({ exercise_name: it.exercise, result })
  }
  return [results, raise]
}

/** [weekKey, week] of the current cycle week, as getTodayPlan picks it. */
export async function currentPlanWeek(planData, userId) {
  const plan = planData.plan
  const today = await userToday(userId)
  let wk = repo.currentWeekKey(planData, planData.start_date || today, today)
  if (!plan[wk] || !Object.keys(plan[wk]).length) wk = 'week_1'
  return [wk, plan[wk] || {}]
}

/** Training days of the current week — for a workout on a rest day. */
export async function planDayOptions(planData, userId) {
  const [, week] = await currentPlanWeek(planData, userId)
  const out = []
  for (const [wd, key] of Object.entries(WEEKDAY_KEY)) {
    const ex = week[key]
    if (Array.isArray(ex) && ex.length) out.push({ key, label: WEEKDAY_RU[wd], exercises: ex.map(exerciseName) })
  }
  return out
}

/** One-off session of a plan day today → [session, error] */
export async function startPlanDay(userId, planData, dayKey) {
  const [wk, week] = await currentPlanWeek(planData, userId)
  const ex = week[dayKey]
  if (!Array.isArray(ex) || !ex.length) return [null, 'bad_day']
  const session = await repo.createExtraSession(userId, `${wk}_${dayKey}`, ex)
  return session ? [session, null] : [null, 'session_exists']
}

/** Workout described in text on a rest day; the session is done at once → [session, results] */
export async function saveFreeWorkout(userId, items, raw) {
  const plan = items.map(it => ({ exercise: it.exercise, sets: it.sets_done ?? null, reps: it.reps_done ?? null, weight: it.weight_done ?? null }))
  const session = await repo.createExtraSession(userId, 'free', plan, 'done')
  if (!session) return [null, null]
  const results = []
  for (const it of items) {
    const result = { sets_done: it.sets_done ?? null, reps_done: it.reps_done ?? null, weight_done: it.weight_done ?? null, completed: true, note: it.note ?? null }
    await logExercise(session.id, userId, it.exercise, null, result, raw)
    results.push({ exercise_name: it.exercise, result })
  }
  return [session, results]
}

export async function recentSessions(userId, limit) {
  return all('SELECT * FROM ai_workout_sessions WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?', [userId, limit])
}
