const tg = (window as any).Telegram?.WebApp

export function getInitData(): string {
  return tg?.initData ?? ''
}

export function getUser() {
  return tg?.initDataUnsafe?.user ?? null
}

export function ready() {
  try {
    tg?.ready()
    tg?.expand()
  } catch { /* not in Telegram — dev mode */ }
}

async function req(path: string, opts: RequestInit = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': getInitData(), ...(opts.headers ?? {}) },
  })
  const body = await res.json().catch(() => ({ ok: false, error: 'bad_response' }))
  if (!res.ok || !body.ok) throw new Error(body.error ?? `http_${res.status}`)
  return body.data
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
  stats: (days = 7) => req(`/api/stats?days=${days}`),
  workout: () => req('/api/workout'),
  workoutStart: () => req('/api/workout/start', { method: 'POST', body: '{}' }),
  workoutLog: (session_id: number, exercise: any, action: 'done' | 'skip', result?: any) =>
    req('/api/workout/log', { method: 'POST', body: JSON.stringify({ session_id, exercise, action, result }) }),
  workoutFinish: (session_id: number) =>
    req('/api/workout/finish', { method: 'POST', body: JSON.stringify({ session_id }) }),
  workoutGenerate: (goal: string, level: string, days: number, notes = '') =>
    req('/api/workout/generate', { method: 'POST', body: JSON.stringify({ goal, level, days, notes }) }),
  workoutSavePlan: (plan: any, mode = 'ai', goal = '', level = '', days = 3) =>
    req('/api/workout/plan', { method: 'POST', body: JSON.stringify({ plan, mode, goal, level, days }) }),
  workoutHistory: (limit = 10) => req(`/api/workout/history?limit=${limit}`),
  aiAsk: (question: string) =>
    req('/api/ai/ask', { method: 'POST', body: JSON.stringify({ question }) }),
  aiAdvice: () => req('/api/ai/advice', { method: 'POST', body: '{}' }),
  aiLast: () => req('/api/ai/last'),
}
