// AI calls. The providers (Atria → GigaChat for photos → Nara → Google) stay
// in Python on the Render worker (GigaChat isn't reachable from here: port 9443
// and the Russian root CA are refused). This module keeps the prompts and the
// parsing from trackcheck/services/ai_service.py and talks to the relay.
//
// Invocations here are capped at ~30 s, so a relay call waits at most ~22 s.
// A job that is still running comes back as { pending: true }; the relay keeps
// working on it and an identical retry (same key) picks up the result — which
// is exactly what the existing «🔄 Попробовать еще раз» buttons do.

import { fetch } from 'sdk'
import { RELAY_URL, RELAY_SECRET } from './secrets.js'
import { stripMarkdown, pyRound, formatMacros, workoutsProgress, fix1, pyVal, pyJson } from './util.js'
import * as repo from './repo.js'
import { all } from './turso.js'

const RELAY = RELAY_URL.replace(/\/+$/, '')
const MAX_WAIT_MS = 22000

// ---- base64 / hashing (no btoa in this runtime) ----

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
export function toBase64(bytes) {
  let out = ''
  let i = 0
  for (; i + 2 < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2]
    out += B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + B64[n & 63]
  }
  if (i < bytes.length) {
    const n = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8)
    out += B64[n >> 18] + B64[(n >> 12) & 63] + (i + 1 < bytes.length ? B64[(n >> 6) & 63] : '=') + '='
  }
  return out
}

export function fromBase64(s) {
  s = String(s).replace(/[^A-Za-z0-9+/]/g, '')
  const out = new Uint8Array(Math.floor(s.length * 3 / 4))
  let o = 0
  for (let i = 0; i < s.length; i += 4) {
    const n = (B64.indexOf(s[i]) << 18) | (B64.indexOf(s[i + 1]) << 12)
      | ((B64.indexOf(s[i + 2] ?? 'A') & 63) << 6) | (B64.indexOf(s[i + 3] ?? 'A') & 63)
    out[o++] = (n >> 16) & 255
    if (i + 2 < s.length) out[o++] = (n >> 8) & 255
    if (i + 3 < s.length) out[o++] = n & 255
  }
  return out.slice(0, o)
}

async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('')
}

// ---- relay ----

/** Last failure reason, like Python's LAST_AI_CALL / _friendly_ai_error(). */
let lastError = ''
export function friendlyAiError() {
  return lastError || '❌ ИИ не вернул ответ (возможно, сработала фильтрация). Попробуй ещё раз.'
}

/**
 * Raw text from the providers (no markdown stripping) or null.
 * opts: maxTokens, thinkOff, ratingKey, image (Uint8Array), stream,
 *       onDelta(textSoFar), onTick(i), userId, waitMs
 * Returns { text } | { text: null, error } | { pending: true }
 */
export async function generate(prompt, opts = {}) {
  const body = {
    prompt,
    max_tokens: opts.maxTokens ?? 8192,
    think_off: !!opts.thinkOff,
    rating_key: !!opts.ratingKey,
    stream: !!opts.stream,
    wait: Math.min(opts.waitMs ?? MAX_WAIT_MS, MAX_WAIT_MS) / 1000,
  }
  if (opts.image) body.image_b64 = toBase64(opts.image)
  body.key = await sha256(JSON.stringify([opts.userId ?? 0, body.prompt, body.max_tokens, body.think_off,
    body.rating_key, body.stream, body.image_b64 ? await sha256(body.image_b64) : '']))
  let res
  try {
    res = await fetch(`${RELAY}/relay/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Relay-Secret': RELAY_SECRET },
      body: JSON.stringify(body),
    })
  } catch (e) {
    lastError = '❌ ИИ-сервис недоступен. Попробуй ещё раз через минуту.'
    console.error('[AI] relay unreachable', e && e.message)
    return { text: null, error: lastError }
  }
  if (!res.ok) {
    lastError = '❌ ИИ-сервис недоступен. Попробуй ещё раз через минуту.'
    console.error('[AI] relay http', res.status, (await res.text()).slice(0, 200))
    return { text: null, error: lastError }
  }
  // NDJSON: {"tick":n} … {"delta":"…"} … then {"done":true,"text":…,"error":…} or {"pending":true}
  const dec = new TextDecoder()
  let buf = '', soFar = ''
  const handle = async (line) => {
    if (!line.trim()) return null
    const ev = JSON.parse(line)
    if (ev.tick !== undefined) { if (opts.onTick) await opts.onTick(ev.tick); return null }
    if (ev.delta !== undefined) { soFar += ev.delta; if (opts.onDelta) await opts.onDelta(soFar); return null }
    return ev
  }
  try {
    for await (const chunk of res.body) {
      buf += dec.decode(chunk, { stream: true })
      let nl
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl)
        buf = buf.slice(nl + 1)
        const ev = await handle(line)
        if (ev) return finish(ev)
      }
    }
    const ev = await handle(buf)
    if (ev) return finish(ev)
  } catch (e) {
    console.error('[AI] relay stream broke', e && e.message)
  }
  lastError = '❌ ИИ не ответил. Попробуй ещё раз.'
  return { text: null, error: lastError }
}

function finish(ev) {
  if (ev.pending) {
    lastError = '⏳ ИИ ещё думает. Нажми «🔄 Попробовать еще раз» через пару секунд.'
    return { pending: true, text: null, error: lastError }
  }
  if (ev.text) return { text: ev.text }
  lastError = ev.error || friendlyAiError()
  return { text: null, error: lastError }
}

/** gemini_generate: text with markdown stripped, or a «❌ …» message. */
export async function geminiGenerate(prompt, maxTokens = 8192, raw = false, opts = {}) {
  const r = await generate(prompt, { maxTokens, ...opts })
  if (!r.text) return r.error || friendlyAiError()
  return raw ? r.text : stripMarkdown(r.text)
}

/** gemini_generate_json: raw text or ''. */
export async function geminiGenerateJson(prompt, maxTokens = 8192, opts = {}) {
  const r = await generate(prompt, { maxTokens, thinkOff: true, ...opts })
  return r.text || ''
}

/** gemini_generate_rating → {rating, comment} | null */
export async function geminiGenerateRating(prompt, maxTokens = 1024, opts = {}) {
  const r = await generate(prompt, { maxTokens, thinkOff: true, ratingKey: true, ...opts })
  if (!r.text) return null
  try {
    const text = r.text.trim().replace(/^```json\s*|\s*```$/g, '').trim()
    const data = JSON.parse(text)
    const rating = Math.max(1, Math.min(10, pyRound(parseFloat(data.rating))))
    if (Number.isNaN(rating)) return null
    const comment = String(data.comment || data.response || '').trim()
    return { rating, comment }
  } catch (e) {
    console.warn('[AI-RATINGS] parse failed', r.text.slice(0, 300))
    return null
  }
}

// ---- prompts (ai_service.py) ----

const CHECK_STYLE = `Как отвечать:
- Сразу суть: 1–3 коротких предложения или до 3 пунктов по одной строке.
- Без вступлений, приветствий, пересказа вопроса, похвалы ради похвалы и общих фраз вроде «важно слушать своё тело».
- Данные пользователя упоминай, только если они прямо относятся к делу.
- Если ответ — «да» или «нет», начни с него.
- Обратись по имени один раз, не больше одного эмодзи.`

export function checkQuestionPrompt(name, context, question) {
  return `Ты — Check, персональный ассистент трекера TrackCheck. Пользователь ${name}.\n\n`
    + `Данные пользователя:\n${context}\n\n`
    + `Вопрос: ${question}\n\n${CHECK_STYLE}`
}

export function checkAdvicePrompt(name, context) {
  return `Ты — Check, персональный ассистент трекера TrackCheck. Пользователь ${name}.\n\n`
    + `Данные пользователя:\n${context}\n\n`
    + 'Дай один совет на сегодня: что главное заметил в данных и один конкретный шаг. '
    + 'Максимум 2–3 коротких предложения, пиши по-русски.\n\n'
    + CHECK_STYLE
}

export function moodPrompt(name, description, fullContext) {
  return `Ты — заботливый персональный трекер-ассистент. Пользователя зовут ${name}.
Он(а) описал(а) свой сегодняшний день и настроение так: "${description}"

Вот что ты ещё знаешь о нём(ней) за последнее время:
${fullContext}

Оцени его(её) настроение сегодня по шкале от 1 до 10 (10 — отличное настроение, 1 — очень плохое).
Затем напиши тёплый отклик по-русски, обращаясь по имени, — максимум 2 коротких предложения, без вступлений и общих фраз:
- если настроение хорошее — коротко порадуйся вместе с ним(ней);
- если настроение так себе или плохое — поддержи и дай один конкретный шаг,
  учитывая контекст выше.
Ответь СТРОГО в формате JSON без пояснений и без markdown:
{"rating": <целое число 1-10>, "response": "<текст отклика>"}`
}

export function foodCaloriesPrompt(description) {
  return `Ты — точный счётчик калорий и БЖУ. Пользователь описывает что он съел (на русском или английском языке).

Твоя задача: посчитать ОБЩИЕ ккал, белки, жиры и углеводы во всём описанном количестве еды.

ПРАВИЛА:
- Если указано количество (2 бургера, 3 яйца, 200г) — умножай соответственно
- Если количество не указано — считай стандартную порцию (тарелка супа ~300мл, второе блюдо ~300-400г, бутерброд ~150г)
- Учитывай ВСЕ компоненты: хлеб, масло, соусы, напитки, гарнир
- Не занижай: реальная еда жирнее и калорийнее чем кажется
- Минимум для полноценного приёма пищи (обед/ужин): 350 ккал
- Перекус может быть 100-300 ккал
- БЖУ должны сходиться с ккал: белки×4 + жиры×9 + углеводы×4 ≈ ккал

Ориентиры (на порцию: ккал белки жиры углеводы):
гречка с курицей = 450 35 12 50, паста карбонара = 680 25 30 75, бургер = 550 28 28 45,
пицца (2 куска) = 600 25 22 75, борщ = 300 12 14 30, салат цезарь с курицей = 520 30 35 20,
омлет 2 яйца = 200 14 15 2, овсянка на молоке = 280 10 8 42, рис с мясом = 500 28 15 62,
шаурма = 650 30 32 60, суши-сет 8шт = 480 20 10 75, протеиновый коктейль = 150 25 2 8,
кофе с молоком = 60 3 3 5, яблоко = 80 0 0 20, банан = 100 1 0 25

Еда: ${description}

Ответь СТРОГО одной строкой из четырёх целых чисел через пробел: ккал белки жиры углеводы (граммы). Никаких слов и единиц. Пример: 450 35 12 50`
}

export const FOOD_PHOTO_PROMPT = `Посмотри на фото еды и оцени калорийность и БЖУ.

Ответь строго в формате: [название блюда] [ккал] [белки] [жиры] [углеводы]
Название — 1-4 слова на русском. Числа — только целые, без единиц (БЖУ в граммах).

Правила оценки:
- Считай реальную порцию на фото, не занижай
- Учитывай видимые соусы, масло, хлеб рядом
- Если несколько блюд — суммируй всё
- белки×4 + жиры×9 + углеводы×4 ≈ ккал

Примеры правильных ответов:
гречка с курицей 480 36 13 52
паста карбонара 650 24 29 72
омлет с сыром 350 22 27 3
бургер и картошка 900 30 45 95
салат цезарь 520 30 35 20`

function parseNutritionNumbers(nums) {
  if (nums.length >= 4) {
    let [kcal, protein, fat, carbs] = nums.slice(-4)
    if (kcal >= 50 && kcal <= 5000 && Math.max(protein, fat, carbs) <= 1000) {
      const macroKcal = protein * 4 + fat * 9 + carbs * 4
      if (macroKcal <= 0) return { calories: kcal, protein: null, fat: null, carbs: null }
      if (Math.abs(macroKcal - kcal) / kcal > 0.2) {
        const k = kcal / macroKcal
        protein *= k; fat *= k; carbs *= k
      }
      return { calories: kcal, protein: pyRound(protein, 1), fat: pyRound(fat, 1), carbs: pyRound(carbs, 1) }
    }
  }
  const valid = nums.filter(n => n >= 50 && n <= 5000)
  if (!valid.length) return null
  return { calories: valid[valid.length - 1], protein: null, fat: null, carbs: null }
}

const numbers = (text) => (String(text).match(/\d+(?:[.,]\d+)?/g) || []).map(n => parseFloat(n.replace(',', '.')))

export function parseFoodEstimate(text) {
  if (!text) return null
  return parseNutritionNumbers(numbers(text))
}

/** → [description, nutrition|null] */
export function parseFoodPhoto(text) {
  let description = 'Блюдо на фото'
  const m = /^([^0-9]+?)(?:\s*\d|$)/.exec(text || '')
  if (m) {
    const desc = m[1].replace(/^[ .,;:-]+|[ .,;:-]+$/g, '')
    if (desc.length >= 2 && desc.length <= 50) description = desc
  }
  return [description, parseNutritionNumbers(numbers(text || ''))]
}

/** estimate_food_nutrition → {calories, protein, fat, carbs} | null | {pending} */
export async function estimateFoodNutrition(description, opts = {}) {
  const r = await generate(foodCaloriesPrompt(description), { maxTokens: 100, thinkOff: true, ...opts })
  if (r.pending) return null
  return parseFoodEstimate(r.text)
}

/** analyze_food_photo → raw text | null */
export async function analyzeFoodPhoto(image, prompt = FOOD_PHOTO_PROMPT, opts = {}) {
  if (!image || !image.length) return null
  const r = await generate(prompt, { maxTokens: 512, image, thinkOff: true, ...opts })
  return r.text || null
}

// ---- body score (body_score_service.py) ----

export const BODY_SCORE_PROMPT = `Ты опытный тренер. Оцени телосложение человека на фото по шкале 1–10.
Шкала: 3 — заметный лишний вес или очень слабая мускулатура; 5 — обычное нетренированное тело;
7 — видно, что человек тренируется (тонус, пропорции, умеренный процент жира);
9–10 — уровень фитнес-модели или спортсмена. Оценивай честно, без лести и без жестокости.

Верни ТОЛЬКО JSON:
{"score": 6,
 "summary": "одно предложение — общее впечатление",
 "strengths": ["сильное место", "ещё одно"],
 "weaknesses": [{"spot": "слабое место", "fix": "что конкретно делать (упражнения, питание)"}]}

1–3 сильных места, 1–3 слабых. Коротко, на «ты».
Если на фото не видно тела человека — верни {"error": "no_body"}.`

export const NO_BODY = 'no_body'

export function parseBodyScore(text) {
  const data = parseJsonResponse(text || '')
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  if (data.error === NO_BODY) return { error: NO_BODY }
  const s = parseFloat(data.score)
  if (Number.isNaN(s)) return null
  const score = Math.max(1, Math.min(10, pyRound(s)))
  const strengths = (data.strengths || []).map(x => String(x).trim()).filter(Boolean).slice(0, 3)
  const weaknesses = []
  for (const w of (data.weaknesses || []).slice(0, 3)) {
    if (w && typeof w === 'object' && String(w.spot || '').trim()) weaknesses.push({ spot: String(w.spot).trim(), fix: String(w.fix || '').trim() })
    else if (typeof w === 'string' && w.trim()) weaknesses.push({ spot: w.trim(), fix: '' })
  }
  return { score, summary: String(data.summary || '').trim(), strengths, weaknesses }
}

/** → parsed result | null (AI failed) | {pending: true} */
export async function rateBodyPhoto(image, opts = {}) {
  const r = await generate(BODY_SCORE_PROMPT, { maxTokens: 2048, image, thinkOff: true, ...opts })
  if (r.pending) return { pending: true }
  return parseBodyScore(r.text)
}

export function formatBodyScore(result) {
  const lines = [`💪 Оценка тела: ${result.score}/10`]
  if (result.summary) lines.push('', result.summary)
  if (result.strengths && result.strengths.length) lines.push('', '✅ Сильные стороны', ...result.strengths.map(s => `• ${s}`))
  if (result.weaknesses && result.weaknesses.length) {
    lines.push('', '🎯 Над чем работать', ...result.weaknesses.map(w => `• ${w.spot}` + (w.fix ? ` — ${w.fix}` : '')))
  }
  lines.push('', 'Оценка идёт в «реализованный потенциал» до следующего фото.')
  return lines.join('\n')
}

/** score_photo_for_bot: rate, save, and return the bot text; failures start with «❌»/«⏳». */
export async function scorePhotoForBot(userId, image) {
  const result = await rateBodyPhoto(image, { userId })
  if (result && result.pending) return friendlyAiError()
  if (result === null) return friendlyAiError()
  if (result.error === NO_BODY) return '❌ На фото не видно тела. Пришли фото в полный рост или по пояс.'
  await repo.saveBodyScore(userId, result)
  return formatBodyScore(result)
}

// ---- context for Check ----

export async function getUserStatsForAi(userId) {
  const [r7, r30, workouts, rank, yesterday, today] = [
    await repo.getRatings(userId, 7), await repo.getRatings(userId, 30),
    await repo.getOrCreateWorkoutData(userId), await repo.getOrCreateRankData(userId),
    await repo.getYesterdayRatings(userId), await repo.getTodayRatings(userId),
  ]
  const avg = (rows) => Object.fromEntries(rows.map(r => [r.category, r.avg_rating]))
  return { today, yesterday, week_avg: avg(r7), month_avg: avg(r30), workouts, rank }
}

/** Python dict repr for {'сон': 7.5, …} as used in a couple of prompts. */
export function pyDict(obj) {
  return '{' + Object.entries(obj).map(([k, v]) => `'${k}': ${Number.isInteger(v) ? v.toFixed(1) : v}`).join(', ') + '}'
}

export async function getFullContextForAi(userId) {
  const lines = []
  const stats = await getUserStatsForAi(userId)
  const fmt = (o) => Object.entries(o).map(([c, v]) => `${c} ${v}/10`).join(', ')
  lines.push(Object.keys(stats.today).length ? 'Рефлексия сегодня: ' + fmt(stats.today) : 'Рефлексия сегодня: ещё не заполнена.')
  if (Object.keys(stats.yesterday).length) lines.push('Рефлексия вчера: ' + fmt(stats.yesterday))
  if (Object.keys(stats.week_avg).length) {
    lines.push('Средние оценки за 7 дней: ' + Object.entries(stats.week_avg).map(([c, v]) => `${c} ${fix1(v)}`).join(', '))
  }

  let profile = null
  try { profile = await repo.getDietProfile(userId) } catch { profile = null }
  if (profile) {
    const todayCal = await repo.getTodayCalories(userId)
    const goal = profile.daily_calories || 0
    lines.push(`Диета: цель ${Math.trunc(goal)} ккал/день, съедено сегодня ${Math.trunc(todayCal)} ккал.`)
    const macros = await repo.getTodayMacros(userId)
    const goals = await repo.getMacroGoals(userId, profile)
    lines.push('БЖУ сегодня / норма, г: ' + [['protein', 'белки'], ['fat', 'жиры'], ['carbs', 'углеводы']]
      .map(([k, l]) => `${l} ${pyRound(macros[k])}/${pyRound(goals[k])}`).join(', '))
    const log = await repo.getTodayFoodLog(userId)
    if (log.length) {
      lines.push('Еда сегодня: ' + log.map(r => {
        const m = formatMacros(r.protein, r.fat, r.carbs)
        return `${r.meal_type}: ${r.food_description} (${Math.trunc(r.calories)} ккал` + (m ? `, ${m})` : ')')
      }).join('; '))
    }
    const lastWeight = await repo.getLastWeight(userId)
    if (lastWeight) lines.push(`Последний зафиксированный вес: ${lastWeight} кг`)
  } else {
    lines.push('Диета: профиль питания ещё не настроен.')
  }

  lines.push(`Тренировки в этом месяце: ${workoutsProgress(stats.workouts || {})}`)
  let recent = []
  try {
    recent = await all(`
      SELECT date, status, skip_reason FROM ai_workout_sessions
      WHERE user_id = ? AND status != 'pending' ORDER BY date DESC LIMIT 5
    `, [userId])
  } catch { recent = [] }
  if (recent.length) {
    lines.push('Последние тренировки: ' + recent.map(s => {
      if (s.status === 'done') return `${s.date}: выполнена`
      if (s.status === 'skipped') return `${s.date}: пропущена${s.skip_reason ? ` (${s.skip_reason})` : ''}`
      return `${s.date}: ${s.status}`
    }).join('; '))
  }

  let tasks = []
  try { tasks = await repo.getTasksForToday(userId) } catch { tasks = [] }
  if (tasks.length) {
    lines.push('Задачи на сегодня: ' + tasks.map(t => `${t.is_priority ? '🔥' : '-'} ${t.title}${t.is_done ? ' ✅' : ''}`).join('; '))
  }
  return lines.join('\n')
}

// ---- JSON from model output ----

export function parseJsonResponse(text) {
  if (!text) return null
  if (text.startsWith('❌') || text.startsWith('Error') || text.startsWith('⏳')) return null
  let clean = text.trim()
  if (clean.includes('```')) {
    const m = /```\s*(?:json)?\s*\n?([\s\S]*?)```/.exec(clean)
    clean = m ? m[1].trim() : clean.replace(/```/g, '').trim()
  }
  const start = clean.indexOf('{'), end = clean.lastIndexOf('}')
  if (start === -1 || end === -1 || start > end) return null
  clean = clean.slice(start, end + 1)
  if (clean.length < 2) return null
  try { return JSON.parse(clean) } catch { /* try fixes */ }
  try { return JSON.parse(clean.replace(/,\s*}/g, '}').replace(/,\s*]/g, ']')) } catch { /* next */ }
  try { return JSON.parse(clean.replace(/'/g, '"')) } catch { /* give up */ }
  return null
}

// ---- workout prompts ----

/** → plan | null | {pending:true} */
export async function geminiGeneratePlan(goal, level, daysPerWeek, notes = '', opts = {}) {
  const keys = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
  const daysExample = {}
  for (const d of keys.slice(0, daysPerWeek)) {
    daysExample[d] = [
      { exercise: 'Упражнение 1', sets: 3, reps: '10', weight: 50 },
      { exercise: 'Упражнение 2', sets: 3, reps: '12', weight: null },
    ]
  }
  const example = pyJsonIndent({ cycle_weeks: 1, week_1: daysExample })
  const prompt = 'Ты фитнес-тренер. Создай план тренировок.\n'
    + `Цель: ${goal}\nУровень: ${level}\nТренировок в неделю: ${daysPerWeek}\n\n`
    + 'Верни ТОЛЬКО валидный JSON строго в этом формате (замени упражнения на реальные):\n'
    + `${example}\n\n`
    + 'Правила:\n'
    + `- Используй ровно ${daysPerWeek} дней из: monday tuesday wednesday thursday friday saturday sunday\n`
    + '- sets — целое число, reps — строка, weight — число или null\n'
    + '- Если нужны чередующиеся недели добавь week_2 и обнови cycle_weeks\n'
    + '- ТОЛЬКО JSON, никакого текста до или после\n'
    + (notes ? `- Учти пожелания пользователя: ${notes}\n` : '')
  const r = await generate(prompt, { maxTokens: 8192, thinkOff: true, ...opts })
  if (r.pending) return { pending: true }
  return parseJsonResponse(r.text || '')
}

/** json.dumps(obj, ensure_ascii=False, indent=2) */
function pyJsonIndent(obj) {
  return JSON.stringify(obj, null, 2)
}

export async function fallbackParsePlan(rawText, opts = {}) {
  const prompt = 'Разбери этот план тренировок в JSON. Даже если формат нестандартный — сделай максимум.\n\n'
    + 'Структура: {"cycle_weeks": N, "week_1": {"monday": [...], ...}}\n'
    + 'Каждое упражнение: {"exercise": "название", "sets": 3, "reps": "10", "weight": 80}\n\n'
    + 'Правила:\n'
    + "- Блоки 'Неделя 1/2/3' внутри дня → разные week_1/week_2/week_3, cycle_weeks = макс номер\n"
    + "- '/' на отдельной строке = граница между неделями в рамках одного дня\n"
    + '- Упражнения без метки недели → дублируй во все недели\n'
    + "- МАХ(20кг) → максимальный вес на 1 повторение: sets:1, reps:'1', weight:20\n"
    + "- '50 повторений' → sets:1, reps:'50', weight:null\n"
    + "- '40 минут' → sets:1, reps:'40 мин', weight:null\n"
    + "- Дроп-сет '2x(60-40)' → sets:2, reps:'до отказа', weight:60\n"
    + 'Только JSON:\n\n'
    + rawText
  const r = await generate(prompt, { maxTokens: 8192, thinkOff: true, ...opts })
  if (r.pending) return { pending: true }
  return parseJsonResponse(r.text || '')
}

export async function geminiParseManualPlan(rawText, opts = {}) {
  const prompt = 'Ты — парсер планов тренировок. Разбери текст и верни ТОЛЬКО валидный JSON, без пояснений.\n\n'
    + '=== СТРУКТУРА ВЫВОДА ===\n'
    + '{\n'
    + '  "cycle_weeks": N,\n'
    + '  "week_1": { "monday": [...], "wednesday": [...], ... },\n'
    + '  "week_2": { ... },\n'
    + '  "week_3": { ... }\n'
    + '}\n\n'
    + 'Каждое упражнение:\n'
    + '{ "exercise": "название", "sets": 3, "reps": "5", "weight": 100 }\n\n'
    + '=== ПРАВИЛА ЧЕРЕДОВАНИЯ ===\n'
    + "Если внутри одного дня есть строки вида 'Неделя 1 - ...', 'Неделя 2 - ...' — это чередование.\n"
    + "Каждый блок 'Неделя N' относится только к week_N этого дня.\n"
    + "Строки БЕЗ метки 'Неделя N' (до первого блока или после последнего) — дублируй во ВСЕ недели этого дня.\n"
    + 'cycle_weeks = максимальный номер недели в тексте. Если меток нет — cycle_weeks:1.\n\n'
    + '=== ФОРМАТЫ УПРАЖНЕНИЙ ===\n'
    + "3x5(110кг)           → sets:3, reps:'5', weight:110\n"
    + "3х11(90кг)           → sets:3, reps:'11', weight:90  (х — русская буква, то же что x)\n"
    + "МАХ(120кг)           → sets:1, reps:'1', weight:120  (максимальный вес на 1 повторение)\n"
    + "МАХ повторений(20кг) → sets:1, reps:'MAX', weight:20\n"
    + "50 повторений        → sets:1, reps:'50', weight:null\n"
    + "2x(от 60кг к 50кг)  → sets:2, reps:'до отказа', weight:60\n"
    + "40 минут             → sets:1, reps:'40 мин', weight:null\n"
    + "BIU / навык / skill  → sets:1, reps:'1', weight:null\n"
    + 'Без веса             → weight:null\n\n'
    + '=== ДНИ НЕДЕЛИ ===\n'
    + 'Понедельник→monday, Вторник→tuesday, Среда→wednesday, Четверг→thursday,\n'
    + 'Пятница→friday, Суббота→saturday, Воскресенье→sunday\n'
    + "Пометки типа 'PUSH', 'PULL', 'LEG' после названия дня — игнорируй.\n\n"
    + '=== ПРИМЕР (3-недельный цикл) ===\n'
    + 'Вход:\n'
    + 'Понедельник:\n'
    + 'Неделя 1 - Жим лёжа - МАХ(120кг)\n'
    + 'Неделя 2 - Жим лёжа - 3x5(110кг)\n'
    + 'Неделя 3 - Жим на наклонной - 3x11(90кг)\n'
    + 'Разгибания трицепса - 3x12(40кг)\n\n'
    + "→ 'Разгибания трицепса' идёт без метки недели — дублируется в week_1, week_2, week_3.\n\n"
    + 'Выход:\n'
    + '{\n'
    + '  "cycle_weeks": 3,\n'
    + '  "week_1": {"monday": [\n'
    + '    {"exercise": "Жим лёжа", "sets": 1, "reps": "1", "weight": 120},\n'
    + '    {"exercise": "Разгибания трицепса", "sets": 3, "reps": "12", "weight": 40}\n'
    + '  ]},\n'
    + '  "week_2": {"monday": [\n'
    + '    {"exercise": "Жим лёжа", "sets": 3, "reps": "5", "weight": 110},\n'
    + '    {"exercise": "Разгибания трицепса", "sets": 3, "reps": "12", "weight": 40}\n'
    + '  ]},\n'
    + '  "week_3": {"monday": [\n'
    + '    {"exercise": "Жим на наклонной", "sets": 3, "reps": "11", "weight": 90},\n'
    + '    {"exercise": "Разгибания трицепса", "sets": 3, "reps": "12", "weight": 40}\n'
    + '  ]}\n'
    + '}\n\n'
    + '=== ТЕКСТ ПОЛЬЗОВАТЕЛЯ ===\n'
    + `${rawText}\n\n`
    + 'Верни ТОЛЬКО JSON:'
  const r = await generate(prompt, { maxTokens: 8192, thinkOff: true, ...opts })
  if (r.pending) return { pending: true }
  return parseJsonResponse(r.text || '')
}

export async function geminiEditPlan(currentPlan, editRequest, opts = {}) {
  const prompt = `Текущий план тренировок (JSON):\n${pyJson(currentPlan)}\n\n`
    + `Запрос пользователя: ${editRequest}\n\n`
    + 'Внеси изменения и верни ТОЛЬКО обновлённый JSON без markdown и пояснений.'
  const r = await generate(prompt, { maxTokens: 8192, thinkOff: true, ...opts })
  if (r.pending) return { pending: true }
  return parseJsonResponse(r.text || '')
}

function cleanJsonish(result) {
  let clean = String(result).trim()
  if (clean.startsWith('```')) clean = clean.replace(/```[a-z]*\n?/g, '').replace(/```/g, '').trim()
  if (!clean.startsWith('{') && !clean.startsWith('[') && (clean.includes('{') || clean.includes('['))) {
    for (const [s, e] of [['{', '}'], ['[', ']']]) {
      if (clean.includes(s) && clean.includes(e)) {
        clean = clean.slice(clean.indexOf(s), clean.lastIndexOf(e) + 1)
        break
      }
    }
  }
  return clean
}

export async function geminiParseExerciseResult(exercise, rawText, opts = {}) {
  const name = exercise.exercise ?? exercise.name ?? 'упражнение'
  const prompt = `Упражнение: ${name}
План: ${pyVal(exercise.sets)} подходов × ${pyVal(exercise.reps)} повторений, вес ${pyVal(exercise.weight)} кг

Пользователь написал: "${rawText}"

Верни ТОЛЬКО JSON:
{
  "sets_done": 3,
  "reps_done": "10",
  "weight_done": 60,
  "completed": true,
  "note": "не добил последний подход"
}

Правила:
- completed: true если выполнил хотя бы частично
- note: короткая заметка только если есть что-то важное, иначе null
- Только JSON`
  const result = await geminiGenerate(prompt, 256, true, opts)
  try {
    return JSON.parse(cleanJsonish(result))
  } catch {
    return { sets_done: null, reps_done: null, weight_done: null, completed: true, note: rawText.slice(0, 100) }
  }
}


export async function geminiParseFreeWorkout(rawText, opts = {}) {
  const prompt = `Пользователь описал, что сделал на тренировке:
"${rawText}"

Верни ТОЛЬКО JSON:
{"exercises": [
  {"exercise": "Жим гантелей лёжа", "sets_done": 3, "reps_done": "10", "weight_done": 24, "note": null}
]}

Правила:
- exercise: нормальное название упражнения на русском, с большой буквы
- reps_done: строка; если повторения по подходам разные — через запятую ("10,10,8")
- для кардио/статики sets_done и reps_done могут быть null, тогда время/дистанцию напиши в note ("5 км за 30 мин")
- weight_done: число в кг или null
- note: только если есть что-то важное, иначе null
- если упражнений нет — пустой список
- Только JSON`
  const parsed = parseJsonResponse(await geminiGenerate(prompt, 1024, true, opts))
  const ex = parsed && typeof parsed === 'object' ? parsed.exercises : null
  if (!Array.isArray(ex)) return []
  return ex.filter(e => e && typeof e === 'object' && e.exercise)
}

export async function geminiMonthlyReview(plan, recentSessions, opts = {}) {
  const prompt = `Ты тренер. Проанализируй план тренировок и последние результаты.

Текущий план:
${pyJson(plan)}

Последние тренировки (краткие результаты):
${pyJson(recentSessions.slice(0, 10))}

Предложи замены упражнений если нужно. Верни ТОЛЬКО JSON:
{
  "changes": [
    {"day": "monday", "week": "week_1", "old_exercise": "Жим лёжа", "new_exercise": "Жим гантелей", "reason": "для разнообразия и проработки стабилизаторов"},
  ],
  "no_changes_needed": false
}

Если менять ничего не нужно — верни {"changes": [], "no_changes_needed": true}.
Только JSON.`
  // raw: the Python bot ran this through strip_markdown, whose `_…_` rule ate the
  // underscores in "old_exercise"/"week_1" — the review then crashed on a KeyError.
  const result = await geminiGenerate(prompt, 1024, true, opts)
  try {
    let clean = result.trim()
    if (clean.startsWith('```')) clean = clean.replace(/```[a-z]*\n?/g, '').replace(/```/g, '').trim()
    return JSON.parse(clean)
  } catch {
    return null
  }
}

export async function analyzeLowRating(userId, category, rating) {
  const name = await repo.getUserName(userId)
  const stats = await getUserStatsForAi(userId)
  const prompt = `Пользователь ${name} поставил ${category} ${rating}/10.
    Его статистика за неделю: ${pyDict(stats.week_avg)}.
    Дай 1 конкретный совет что могло пойти не так и как улучшить. Макс 2 предложения. Обращайся по имени.`
  return geminiGenerate(prompt, 1024, false, { userId })
}
