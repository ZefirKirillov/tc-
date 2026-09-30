import { useEffect, useState } from 'react'
import { api } from './api'

const CATS: Array<[string, string]> = [
  ['сон', '😴 Сон'],
  ['еда', '🍽 Еда'],
  ['активность', '💪 Активность'],
  ['зависание', '🎮 Зависание'],
  ['настрой', '🎯 Настрой'],
]

function bar(rating: number) {
  const filled = Math.round(rating / 2)
  return '▓'.repeat(filled) + '░'.repeat(5 - filled)
}

export default function App() {
  const [me, setMe] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [pending, setPending] = useState<string | null>(null)

  useEffect(() => {
    api.me().then(setMe).catch((e) => setErr(String(e.message ?? e)))
  }, [])

  async function rate(cat: string, val: number) {
    setPending(cat)
    try {
      const res = await api.saveRating(cat, val)
      setMe((m: any) => ({ ...m, today_ratings: res.ratings }))
    } catch (e: any) {
      setErr(String(e.message ?? e))
    } finally {
      setPending(null)
    }
  }

  if (err && !me) return <div style={s.page}><p>⚠️ {err}</p><p style={s.hint}>Открой через Telegram (кнопка Mini App).</p></div>
  if (!me) return <div style={s.page}><p>Загрузка…</p></div>

  return (
    <div style={s.page}>
      <h2 style={s.h}>TrackCheck {me.rank?.emoji}</h2>
      <p style={s.sub}>{me.rank?.name} · 🔥 {me.streak} дней · ✨ {me.rank?.total_sparks}/{me.rank?.next_total}</p>
      <p style={s.sub}>🏋️ {me.workout?.current_count}/{me.workout?.monthly_goal} · 🍽 {Math.round(me.diet?.today_calories ?? 0)}/{Math.round(me.diet?.daily_goal ?? 0)}</p>
      {err && <p style={s.err}>{err}</p>}
      {CATS.map(([key, label]) => {
        const cur = me.today_ratings?.[key] ?? 0
        return (
          <div key={key} style={s.card}>
            <div style={s.row}><span>{label}</span><span style={s.bar}>{bar(cur)} {cur || '–'}</span></div>
            <div style={s.btns}>
              {[1,2,3,4,5,6,7,8,9,10].map((v) => (
                <button key={v} disabled={pending === key} onClick={() => rate(key, v)}
                  style={{ ...s.btn, ...(cur === v ? s.btnActive : {}) }}>{v}</button>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  page: { fontFamily: 'system-ui', padding: 16, maxWidth: 480, margin: '0 auto', background: 'var(--tg-theme-bg-color, #fff)', color: 'var(--tg-theme-text-color, #000)', minHeight: '100vh' },
  h: { margin: '8px 0 4px' },
  sub: { margin: '2px 0', opacity: 0.8 },
  err: { color: 'red' },
  hint: { opacity: 0.7, fontSize: 14 },
  card: { border: '1px solid #ddd', borderRadius: 12, padding: 12, marginTop: 12 },
  row: { display: 'flex', justifyContent: 'space-between', marginBottom: 8 },
  bar: { fontFamily: 'monospace' },
  btns: { display: 'flex', gap: 4, flexWrap: 'wrap' },
  btn: { width: 30, height: 30, borderRadius: 8, border: '1px solid #ccc', background: '#f5f5f5' },
  btnActive: { background: '#31b545', color: '#fff', borderColor: '#31b545' },
}
