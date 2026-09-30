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
}
