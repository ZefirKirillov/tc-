// trackcheck/utils/formatting.py, utils/validation.py and
// services/gamification_service.py.

import { RANKS, WEEKDAY_NAMES } from './config.js'
import { daysBetween, isDateStr } from './dates.js'

// ---- Python-compatible number helpers ----

/** Python 3 round(): half to even. */
export function pyRound(x, nd = 0) {
  if (x === null || x === undefined || Number.isNaN(x)) return x
  const m = Math.pow(10, nd)
  const v = x * m
  const r = Math.round(v)
  const diff = Math.abs(v - Math.trunc(v))
  let out = r
  if (Math.abs(diff - 0.5) < 1e-9) out = 2 * Math.round(v / 2)
  return nd ? out / m : out
}

/** Python int(x) for floats: truncate toward zero. */
export const pyInt = (x) => Math.trunc(Number(x) || 0)

/** Python f"{x:.1f}" */
export const fix1 = (x) => (Number(x) || 0).toFixed(1)

/** Number as Python prints a float/int value (80.0 stays "80.0" only if we know it's float — we don't). */
export const num = (x) => {
  if (x === null || x === undefined) return 'None'
  return String(x)
}

/** Length in code points, like Python len(). */
export const plen = (s) => Array.from(s || '').length
export const pslice = (s, a, b) => Array.from(s || '').slice(a, b).join('')

export function plural(n, one, few, many) {
  n = Math.abs(n) % 100
  if (n >= 11 && n <= 19) return many
  n %= 10
  return n === 1 ? one : (n >= 2 && n <= 4 ? few : many)
}

// ---- formatting.py ----

export function createNewProgressBar(current, maxVal = 10) {
  const filled = Math.min(current, maxVal)
  const empty = maxVal - filled
  return '🔳'.repeat(Math.max(0, filled)) + '◼️'.repeat(Math.max(0, empty))
}

export function createShortProgressBar(rating, total = 5) {
  let filled = pyRound(rating / 10 * total)
  filled = Math.min(filled, total)
  const empty = total - filled
  return '🔳'.repeat(Math.max(0, filled)) + '◼️'.repeat(Math.max(0, empty))
}

export function createWorkoutProgressBar(current, goal) {
  if (goal === 0) return '◼️'.repeat(12) + ' 0%'
  const percentage = Math.min(current / goal, 1.0)
  const filled = Math.trunc(12 * percentage)
  const empty = 12 - filled
  return '🔳'.repeat(filled) + '◼️'.repeat(empty) + ` ${Math.trunc(percentage * 100)}%`
}

function isEmoji(ch) {
  const cp = ch.codePointAt(0)
  return (cp >= 0x1F300 && cp <= 0x1FAFF) || (cp >= 0x2600 && cp <= 0x27BF) || (cp >= 0xFE00 && cp <= 0xFE0F)
}

/** Strip markdown and extra emoji from AI answers. */
export function stripMarkdown(text) {
  text = String(text ?? '')
  text = text.replace(/\*\*([\s\S]+?)\*\*/g, '$1')
  text = text.replace(/\*([\s\S]+?)\*/g, '$1')
  text = text.replace(/__([\s\S]+?)__/g, '$1')
  text = text.replace(/_([\s\S]+?)_/g, '$1')
  text = text.replace(/^#{1,6}\s+/gm, '')
  const result = []
  let prevEmoji = false
  for (const ch of text) {
    if (isEmoji(ch)) {
      if (!prevEmoji) result.push(ch)
      prevEmoji = true
    } else {
      prevEmoji = false
      result.push(ch)
    }
  }
  return result.join('').split('\n').map(line => {
    let stripped = line.trimStart()
    stripped = stripped.replace(/^[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]+\s*/u, '')
    const indent = line.length - line.trimStart().length
    return ' '.repeat(indent) + stripped
  }).join('\n')
}

export function daysLeftStr(deadline, today) {
  if (!isDateStr(deadline) || !today) return ''
  const diff = daysBetween(today, deadline)
  if (diff < 0) return 'просрочена!'
  if (diff === 0) return 'сегодня!'
  if (diff === 1) return 'завтра'
  return `${diff} дн.`
}

export function formatRepeatDays(repeatDays) {
  try {
    return String(repeatDays).split(',').filter(d => /^\d+$/.test(d.trim()))
      .map(d => WEEKDAY_NAMES[Number(d)]).filter(Boolean).join(', ')
  } catch { return '' }
}

export function workoutsProgress(workoutData) {
  const data = workoutData || {}
  const count = data.current_count || 0
  const goal = data.monthly_goal || 0
  return goal ? `${count}/${goal}` : String(count)
}

export function formatMacros(protein, fat, carbs) {
  if (protein == null && fat == null && carbs == null) return ''
  return `Б ${pyRound(protein || 0)} · Ж ${pyRound(fat || 0)} · У ${pyRound(carbs || 0)} г`
}

export const MACRO_KEYS = ['protein', 'fat', 'carbs']

export function nutritionMacros(nutrition) {
  if (nutrition.protein == null) return null
  return { protein: nutrition.protein, fat: nutrition.fat, carbs: nutrition.carbs }
}

export function foodConfirmText(description, calories, macros, approx = false) {
  let text = `🍽 Ты съел: ${description}\n🔢 Калории: ${approx ? '~' : ''}${pyInt(calories)} ккал`
  if (macros) text += `\n🥩 БЖУ: ${formatMacros(macros.protein, macros.fat, macros.carbs)}`
  return text + '\n\nВсё верно?'
}

// ---- validation.py ----

export function parseRepsInput(repsInput) {
  repsInput = String(repsInput).trim()
  const asInt = (s) => (/^[+-]?\d+$/.test(s.trim()) ? parseInt(s.trim(), 10) : NaN)
  if (repsInput.toLowerCase().includes('x')) {
    const parts = repsInput.toLowerCase().split('x')
    if (parts.length === 2) {
      const sets = asInt(parts[0]), per = asInt(parts[1])
      if (!Number.isNaN(sets) && !Number.isNaN(per)) return [sets, Array(Math.max(0, sets)).fill(per)]
    }
  }
  if (repsInput.includes(' ')) {
    const list = repsInput.split(/\s+/).filter(Boolean).map(asInt)
    if (list.every(n => !Number.isNaN(n))) return [list.length, list]
  }
  if (repsInput.includes(',')) {
    const list = repsInput.split(',').map(asInt)
    if (list.every(n => !Number.isNaN(n))) return [list.length, list]
  }
  const reps = asInt(repsInput)
  if (!Number.isNaN(reps)) return [1, [reps]]
  throw new Error('Неверный формат')
}

export function formatGoalButtonText(exercise) {
  if (exercise.ex_type === 'strength') {
    const { target_sets, target_reps, target_weight } = exercise
    if (target_sets && target_reps) {
      return `🎯 Цель достигнута (${target_sets}х${target_reps}${target_weight ? ` +${target_weight}кг` : ''})`
    }
  } else {
    const { target_distance, target_duration } = exercise
    if (target_distance && target_duration) return `🎯 Цель достигнута (${target_distance}км / ${target_duration}мин)`
  }
  return null
}

// ---- gamification_service.py ----

export function getCurrentRank(totalSparks) {
  let current = 1
  for (const id of Object.keys(RANKS).map(Number).sort((a, b) => a - b)) {
    if (totalSparks >= RANKS[id].sparks_needed) current = id
    else break
  }
  return current
}

export function getSparksForNextRank(currentRank, totalSparks) {
  if (currentRank >= 8) return [0, totalSparks]
  const next = RANKS[currentRank + 1].sparks_needed
  return [next - totalSparks, next]
}

const rank = (id) => RANKS[id] || RANKS[1]
export const getRankEmoji = (id) => rank(id).emoji
export const getRankName = (id) => rank(id).name
export const getRankMotivation = (id) => rank(id).motivation

// ---- Python int()/float() on user input: NaN when Python would raise ValueError ----

export function pyIntParse(s) {
  const t = String(s ?? '').trim().replace(/_/g, '')
  return /^[+-]?\d+$/.test(t) ? parseInt(t, 10) : NaN
}

export function pyFloatParse(s) {
  const t = String(s ?? '').trim().replace(/_/g, '')
  if (/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(t)) return parseFloat(t)
  if (/^[+-]?(inf|infinity)$/i.test(t)) return t.startsWith('-') ? -Infinity : Infinity
  if (/^[+-]?nan$/i.test(t)) return NaN // Python accepts "nan"; callers treat NaN as invalid
  return NaN
}

/** A value as a Python f-string shows it: None for null/undefined. */
export const pyVal = (v) => (v === null || v === undefined ? 'None' : String(v))

/** A float as Python's str() shows it: 80 → "80.0", 52.5 → "52.5", null → "None".
 *  For values Python holds as float: float() of user input, REAL columns. */
export function pyFloat(x) {
  if (x === null || x === undefined) return 'None'
  const n = Number(x)
  if (!Number.isFinite(n)) return n > 0 ? 'inf' : n < 0 ? '-inf' : 'nan'
  if (Number.isInteger(n) && Math.abs(n) < 1e16) return n.toFixed(1)
  return String(n)
}

/** json.dumps(obj, ensure_ascii=False): ", " and ": " separators, like the Python bot wrote. */
export function pyJson(v) {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : (Number.isNaN(v) ? 'NaN' : v > 0 ? 'Infinity' : '-Infinity')
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'string') return JSON.stringify(v)
  if (Array.isArray(v)) return '[' + v.map(pyJson).join(', ') + ']'
  return '{' + Object.entries(v).filter(([, x]) => x !== undefined).map(([k, x]) => `${JSON.stringify(k)}: ${pyJson(x)}`).join(', ') + '}'
}
