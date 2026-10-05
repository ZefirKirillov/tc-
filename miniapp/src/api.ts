import { tg } from './tg'

export function getInitData(): string {
  return tg?.initData ?? ''
}

// Server now returns {ok, error, message} — surface the Russian message.
// A few codes come without a message (401 from the auth decorator, proxies).
const FALLBACK: Record<string, string> = {
  unauthorized: 'Открой TrackCheck через Telegram — кнопка Mini App.',
  bad_response: 'Сервер ответил что-то странное. Попробуй ещё раз.',
}

function fail(body: any, status: number): ApiError {
  const code = body.error ?? `http_${status}`
  const msg = body.message ?? FALLBACK[code] ?? (status >= 500 ? 'Сервер временно недоступен. Попробуй позже.' : code)
  return new ApiError(code, msg)
}

export function isNetworkError(e: unknown): boolean {
  return e instanceof ApiError && e.code === 'network'
}
export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

async function req(path: string, opts: RequestInit = {}) {
  let res: Response
  try {
    res = await fetch(path, {
      ...opts,
      headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': getInitData(), ...(opts.headers ?? {}) },
    })
  } catch {
    throw new ApiError('network', 'Нет соединения. Проверь интернет и попробуй ещё раз.')
  }
  const body = await res.json().catch(() => ({ ok: false, error: 'bad_response' }))
  if (!res.ok || !body.ok) throw fail(body, res.status)
  return body.data
}

// Multipart photo upload (auth via header, not body).
async function reqPhoto(path: string, file: File) {
  const form = new FormData()
  form.append('photo', file)
  let res: Response
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: { 'X-Telegram-Init-Data': getInitData() },
      body: form,
    })
  } catch {
    throw new ApiError('network', 'Нет соединения. Проверь интернет и попробуй ещё раз.')
  }
  const body = await res.json().catch(() => ({ ok: false, error: 'bad_response' }))
  if (!res.ok || !body.ok) throw fail(body, res.status)
  return body.data
}

export function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  return String((e as any)?.message ?? e)
}

export const api = {
  me: () => req('/api/me'),
  ratings: () => req('/api/ratings'),
  saveRating: (category: string, rating: number) =>
    req('/api/ratings', { method: 'POST', body: JSON.stringify({ category, rating }) }),
  tasks: () => req('/api/tasks'),
  addTask: (title: string, is_priority = false, deadline: string | null = null, repeat_days: number[] | null = null) =>
    req('/api/tasks', { method: 'POST', body: JSON.stringify({ title, is_priority, deadline, repeat_days }) }),
  doneTask: (id: number) => req(`/api/tasks/${id}/done`, { method: 'POST', body: '{}' }),
  deleteTask: (id: number) => req(`/api/tasks/${id}`, { method: 'DELETE' }),
  diet: () => req('/api/diet'),
  logFood: (description: string, calories: number, meal = 'Еда') =>
    req('/api/diet/log', { method: 'POST', body: JSON.stringify({ description, calories, meal }) }),
  dietPhoto: (file: File) => reqPhoto('/api/diet/photo', file),
  dietProfile: (profile: Record<string, unknown>) =>
    req('/api/diet/profile', { method: 'POST', body: JSON.stringify(profile) }),
  body: () => req('/api/body'),
  saveBody: (weight: number | null, body_fat: number | null) =>
    req('/api/body', { method: 'POST', body: JSON.stringify({ weight, body_fat }) }),
  stats: (days = 7) => req(`/api/stats?days=${days}`),
  workout: () => req('/api/workout'),
  workoutStart: () => req('/api/workout/start', { method: 'POST', body: '{}' }),
  workoutLog: (session_id: number, exercise: any, action: 'done' | 'skip', result?: any) =>
    req('/api/workout/log', { method: 'POST', body: JSON.stringify({ session_id, exercise, action, result }) }),
  workoutLogText: (session_id: number, exercise: any, text: string) =>
    req('/api/workout/log-text', { method: 'POST', body: JSON.stringify({ session_id, exercise, text }) }),
  workoutFinish: (session_id: number) =>
    req('/api/workout/finish', { method: 'POST', body: JSON.stringify({ session_id }) }),
  workoutGenerate: (goal: string, level: string, days: number, notes = '') =>
    req('/api/workout/generate', { method: 'POST', body: JSON.stringify({ goal, level, days, notes }) }),
  workoutSavePlan: (plan: any, mode = 'ai', goal = '', level = '', days = 3) =>
    req('/api/workout/plan', { method: 'POST', body: JSON.stringify({ plan, mode, goal, level, days }) }),
  workoutParsePlan: (text: string) =>
    req('/api/workout/parse-plan', { method: 'POST', body: JSON.stringify({ text }) }),
  workoutReview: () => req('/api/workout/review', { method: 'POST', body: '{}' }),
  workoutApplyReview: (accepted: any[]) =>
    req('/api/workout/apply-review', { method: 'POST', body: JSON.stringify({ accepted }) }),
  workoutHistory: (limit = 10) => req(`/api/workout/history?limit=${limit}`),
  aiAsk: (question: string) =>
    req('/api/ai/ask', { method: 'POST', body: JSON.stringify({ question }) }),
  aiAdvice: () => req('/api/ai/advice', { method: 'POST', body: '{}' }),
  aiLast: () => req('/api/ai/last'),
}

// In-memory cache of the last response per screen: re-opening a tab renders the
// previous data instantly while a fresh request runs in the background.
const memo = new Map<string, unknown>()
export function peek<T = any>(key: string): T | undefined {
  return memo.get(key) as T | undefined
}
export function keep<T>(key: string, value: T): T {
  memo.set(key, value)
  return value
}
