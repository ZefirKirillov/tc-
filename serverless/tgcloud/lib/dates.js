// Calendar dates as 'YYYY-MM-DD' strings and the user's local time, like
// trackcheck/utils/dates.py. Weekdays are Python-style: Monday = 0.

import { one, execute } from './turso.js'
import { DEFAULT_TIMEZONE } from './config.js'

const TZ_TTL_MS = 5 * 60 * 1000
const tzCache = new Map() // user_id -> { tz, at }

const fmtCache = new Map()
function formatter(tz) {
  let f = fmtCache.get(tz)
  if (!f) {
    f = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    })
    fmtCache.set(tz, f)
  }
  return f
}

export function isValidTimezone(tz) {
  try { formatter(tz).format(new Date()); return true } catch { return false }
}

export async function getUserTimezone(userId) {
  const c = tzCache.get(userId)
  if (c && Date.now() - c.at < TZ_TTL_MS) return c.tz
  const row = await one('SELECT timezone FROM user_settings WHERE user_id = ?', [userId])
  const tz = row && row.timezone && isValidTimezone(row.timezone) ? row.timezone : DEFAULT_TIMEZONE
  tzCache.set(userId, { tz, at: Date.now() })
  return tz
}

export async function setUserTimezone(userId, tz) {
  if (!isValidTimezone(tz)) throw new Error(`Unknown timezone: ${tz}`)
  await execute(`
    INSERT INTO user_settings (user_id, timezone) VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone
  `, [userId, tz])
  tzCache.set(userId, { tz, at: Date.now() })
}

/** Wall-clock parts of `instant` in `tz`. */
export function nowIn(tz, instant = new Date()) {
  const p = {}
  for (const part of formatter(tz).formatToParts(instant)) p[part.type] = part.value
  const date = `${p.year}-${p.month}-${p.day}`
  return {
    date,
    ym: date.slice(0, 7),
    year: Number(p.year), month: Number(p.month), day: Number(p.day),
    hour: Number(p.hour), minute: Number(p.minute), second: Number(p.second),
    weekday: weekdayOf(date),
    time: `${p.hour}:${p.minute}`,
  }
}

export async function userNow(userId) {
  return nowIn(await getUserTimezone(userId))
}

export async function userToday(userId) {
  return (await userNow(userId)).date
}

export async function userWeekday(userId) {
  return (await userNow(userId)).weekday
}

// ---- pure 'YYYY-MM-DD' arithmetic (UTC-based, no DST surprises) ----

function toUTC(d) {
  const [y, m, day] = d.split('-').map(Number)
  return Date.UTC(y, m - 1, day)
}

function fromUTC(ms) {
  return new Date(ms).toISOString().slice(0, 10)
}

export function addDays(d, n) {
  return fromUTC(toUTC(d) + n * 86400000)
}

/** b - a in whole days. */
export function daysBetween(a, b) {
  return Math.round((toUTC(b) - toUTC(a)) / 86400000)
}

/** Monday = 0 … Sunday = 6. */
export function weekdayOf(d) {
  return (new Date(toUTC(d)).getUTCDay() + 6) % 7
}

export function isDateStr(s) {
  if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return false
  return fromUTC(toUTC(s)) === s
}

export function daysInMonth(year, month) {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

export function ymd(year, month, day) {
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

/** '2026-10-18' → '18.10' */
export function ddmm(d) {
  return `${d.slice(8, 10)}.${d.slice(5, 7)}`
}

/** '2026-10-18' → '18.10.2026' */
export function ddmmyyyy(d) {
  return `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`
}

/** Monday of the week containing d. */
export function weekStart(d) {
  return addDays(d, -weekdayOf(d))
}

/** UTC now as 'YYYY-MM-DD HH:MM:SS' (SQLite CURRENT_TIMESTAMP format). */
export function utcTimestamp(instant = new Date()) {
  return instant.toISOString().slice(0, 19).replace('T', ' ')
}
