// trackcheck/services/potential_service.py — «реализованный потенциал» (40 points a day)
// and the explanations of its plateaus and drawbacks.

import * as repo from './repo.js'
import { userToday, addDays } from './dates.js'
import { pyRound, pyJson } from './util.js'
import { generate, parseJsonResponse } from './ai.js'

export const MAX_TOTAL = 40
const CATEGORIES = ['сон', 'зависание', 'настрой', 'еда', 'активность']
const WELLBEING = ['сон', 'зависание', 'настрой']
const DROP = 6, PEAK_WINDOW = 5, PLATEAU_MIN = 5, PLATEAU_BAND = 3, PLATEAU_CEILING = 34
const LOOKBACK_DAYS = 30, MAX_NEW_NOTES = 4

const LABELS = { 'сон': 'сон', 'зависание': 'зависание', 'настрой': 'настрой', 'еда': 'питание', 'активность': 'тренировка', 'тело': 'тело' }
const TIPS = {
  'сон': 'Ложись в одно и то же время и убирай телефон за час до сна.',
  'зависание': 'Поставь лимит на соцсети и игры и держи телефон вне досягаемости, пока работаешь.',
  'настрой': 'Начинай день с одной маленькой задачи, которую точно доделаешь.',
  'еда': 'Планируй приёмы пищи заранее и вноси еду сразу — так проще попадать в норму.',
  'активность': 'Не пропускай тренировки подряд: тяжело — сделай облегчённую версию, но сделай.',
  'тело': 'Тело меняется медленно: держи питание и тренировки ровными и обновляй фото раз в 2–4 недели.',
}

const r1 = (x) => pyRound(x + 1e-9, 1)

/** bisect.bisect_right */
function bisectRight(arr, x) {
  let lo = 0, hi = arr.length
  while (lo < hi) { const mid = (lo + hi) >> 1; if (x < arr[mid]) hi = mid; else lo = mid + 1 }
  return lo
}

export function buildSeries(dates, ratingsByDate, bodyHistory) {
  const bodyDates = bodyHistory.map(([d]) => d)
  const known = Object.fromEntries(CATEGORIES.map(c => [c, null]))
  let last = null
  const out = []
  for (const date of dates) {
    const day = Object.fromEntries(Object.entries(ratingsByDate[date] || {}).filter(([c]) => CATEGORIES.includes(c)))
    if (!Object.keys(day).length) {
      out.push(last === null ? { date, total: null, filled: true, parts: null, values: null } : { ...last, date, filled: true })
      continue
    }
    Object.assign(known, day)
    const i = bisectRight(bodyDates, date)
    const body = i ? bodyHistory[i - 1][1] : 0
    const wb = WELLBEING.map(c => known[c]).filter(v => v !== null)
    const parts = {
      wellbeing: wb.length ? r1(wb.reduce((a, b) => a + b, 0) / wb.length) : 0,
      diet: known['еда'] || 0,
      training: known['активность'] || 0,
      body,
    }
    const values = { ...Object.fromEntries(CATEGORIES.map(c => [c, known[c]])), 'тело': body || null }
    last = { date, total: r1(Object.values(parts).reduce((a, b) => a + b, 0)), filled: false, parts, values }
    out.push(last)
  }
  return out
}

export function findSegments(series) {
  const pts = series.filter(p => !p.filled && p.total !== null).map(p => [p.date, p.total])
  const vals = pts.map(([, v]) => v)
  const n = vals.length
  const segs = []
  const inDrawback = Array(n).fill(false)
  let i = 1, floor = 0
  while (i < n) {
    const lo = Math.max(floor, i - PEAK_WINDOW)
    const peak = Math.max(...vals.slice(lo, i))
    let p = lo
    for (let k = lo; k < i; k++) if (vals[k] === peak) p = k
    if (vals[i] <= peak - DROP) {
      let j = i
      while (j + 1 < n && vals[j + 1] < vals[j]) j++
      segs.push({ kind: 'drawback', start: pts[p][0], end: pts[j][0], from: vals[p], to: vals[j] })
      for (let k = p; k <= j; k++) inDrawback[k] = true
      floor = j
      i = j + 1
    } else i++
  }
  i = 0
  while (i < n) {
    if (inDrawback[i]) { i++; continue }
    let j = i
    while (j + 1 < n && !inDrawback[j + 1]
      && Math.max(...vals.slice(i, j + 2)) - Math.min(...vals.slice(i, j + 2)) <= PLATEAU_BAND) j++
    const mean = vals.slice(i, j + 1).reduce((a, b) => a + b, 0) / (j - i + 1)
    if (j - i + 1 >= PLATEAU_MIN && mean < PLATEAU_CEILING) {
      segs.push({ kind: 'plateau', start: pts[i][0], end: pts[j][0], from: vals[i], to: vals[j], level: r1(mean) })
      i = j + 1
    } else i++
  }
  return segs.sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0))
}

const segmentDays = (series, seg) => series.filter(p => seg.start <= p.date && p.date <= seg.end && !p.filled)

const sortKeys = (o) => (o && typeof o === 'object' && !Array.isArray(o)
  ? Object.fromEntries(Object.keys(o).sort().map(k => [k, sortKeys(o[k])]))
  : Array.isArray(o) ? o.map(sortKeys) : o)

/** Same hash as Python, so notes saved by either bot are found by both. */
export async function segmentSignature(series, seg) {
  const raw = pyJson(sortKeys(segmentDays(series, seg).map(p => [p.date, p.values])))
  const buf = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(`${seg.kind}|${raw}`))
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 16)
}

function fmt(x) {
  x = r1(Number(x))
  return (Number.isInteger(x) ? String(x) : String(x)).replace('.', ',')
}

export function segmentFacts(series, seg) {
  const days = segmentDays(series, seg)
  const cats = [...CATEGORIES, 'тело']
  if (seg.kind === 'drawback') {
    const first = days[0].values
    const pool = days.slice(1).length ? days.slice(1) : days
    let trough = pool[0]
    for (const p of pool) if (p.total < trough.total) trough = p
    const t = trough.values
    const changes = cats.filter(c => first[c] != null && t[c] != null && t[c] < first[c]).map(c => [c, first[c], t[c]])
    changes.sort((a, b) => (a[2] - a[1]) - (b[2] - b[1]))
    return { changes }
  }
  const avgs = cats.map(c => {
    const vs = days.map(p => p.values[c]).filter(v => v != null)
    return [c, vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : 0]
  })
  avgs.sort((a, b) => a[1] - b[1])
  return { weakest: avgs }
}

export function fallbackNote(series, seg) {
  const facts = segmentFacts(series, seg)
  let what, cat
  if (seg.kind === 'drawback') {
    const top = facts.changes.slice(0, 2)
    what = `Потенциал упал с ${fmt(seg.from)} до ${fmt(seg.to)} из ${MAX_TOTAL}`
    if (top.length) what += ': ' + top.map(([c, a, b]) => `${LABELS[c]} ${fmt(a)}→${fmt(b)}`).join(', ')
    cat = top.length ? top[0][0] : 'настрой'
  } else {
    const n = segmentDays(series, seg).length
    const weak = facts.weakest.slice(0, 2)
    what = `${n} дн. на уровне ~${fmt(seg.level)} из ${MAX_TOTAL}, слабее всего — `
      + weak.map(([c, v]) => `${LABELS[c]} (≈${fmt(v)}/10)`).join(' и ')
    cat = weak.length ? weak[0][0] : 'настрой'
  }
  return { what: what + '.', fix: TIPS[cat] }
}

export function notePrompt(name, series, seg) {
  const days = segmentDays(series, seg)
  const table = days.map(p => `${p.date}: итог ${fmt(p.total)}/40; `
    + Object.entries(p.values).filter(([, v]) => v !== null).map(([c, v]) => `${LABELS[c]} ${fmt(v)}`).join(', ')).join('\n')
  const kind = seg.kind === 'drawback'
    ? `СПАД: с ${fmt(seg.from)} до ${fmt(seg.to)} из 40`
    : `ПЛАТО: ${days.length} дн. на уровне ~${fmt(seg.level)} из 40, без роста`
  return `Ты Check — коуч в трекере привычек. Пользователь: ${name}.
Каждый день он получает «реализованный потенциал» из 40 баллов:
самочувствие (среднее сна, зависания и настроя, 0–10) + питание (0–10, насколько попал в норму калорий)
+ тренировка (0–10, насколько выполнил план; 5 — день отдыха) + тело (оценка фото, 0–10).
Все оценки: 10 — лучше всего. «Зависание» 10 = почти не залипал в телефон и игры.

На графике найден отрезок — ${kind}.
Оценки по дням:
${table}

Объясни, что произошло (по цифрам, какие части потянули вниз или стоят на месте),
и как не допустить такого снова — один-два конкретных действия.
Пиши на «ты», коротко, без воды. Верни ТОЛЬКО JSON:
{"what": "1–2 предложения: что произошло", "fix": "1–2 предложения: что делать"}`
}

async function load(userId, days) {
  const span = days + LOOKBACK_DAYS
  const today = await userToday(userId)
  const dates = Array.from({ length: span }, (_, i) => addDays(today, -(span - 1 - i)))
  const byDate = {}
  for (const r of await repo.getDailyRatings(userId, span)) (byDate[r.day_date] ||= {})[r.category] = r.rating
  return buildSeries(dates, byDate, await repo.getBodyScoreHistory(userId)).slice(-days)
}

export async function getPotential(userId, days) {
  const series = await load(userId, days)
  const notes = await repo.getPotentialNotes(userId)
  const segments = []
  for (const seg of findSegments(series)) {
    const signature = await segmentSignature(series, seg)
    segments.push({ ...seg, signature, note: notes.get([seg.kind, seg.start, seg.end, signature].join('|')) || null })
  }
  return { max: MAX_TOTAL, series, segments }
}

/** Write the missing notes (AI, in parallel so it fits the time limit); rules-based fallback otherwise. */
export async function explainSegments(userId, days) {
  const data = await getPotential(userId, days)
  const { series } = data
  const missing = data.segments.filter(s => s.note === null).slice(-MAX_NEW_NOTES)
  const name = await repo.getUserName(userId)
  await Promise.all(missing.map(async (seg) => {
    const r = await generate(notePrompt(name, series, seg), { maxTokens: 1024, thinkOff: true, userId, waitMs: 20000 })
    const parsed = parseJsonResponse(r.text || '') || {}
    const what = String(parsed.what || '').trim(), fix = String(parsed.fix || '').trim()
    if (what && fix) {
      await repo.savePotentialNote(userId, seg.kind, seg.start, seg.end, seg.signature, what.slice(0, 600), fix.slice(0, 600))
      seg.note = { what: what.slice(0, 600), fix: fix.slice(0, 600) }
    }
  }))
  for (const seg of data.segments) if (seg.note === null) seg.note = { ...fallbackNote(series, seg), fallback: true }
  return data.segments
}
