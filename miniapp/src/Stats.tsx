import { useEffect, useState } from 'react'
import { api } from './api'
import { s } from './styles'

const SHORT: Record<string, string> = { 'сон': '😴', 'еда': '🍽', 'активность': '💪', 'зависание': '🎮', 'настрой': '🎯' }

export default function Stats({ onErr }: { onErr: (e: string) => void }) {
  const [data, setData] = useState<any>(null)
  const [days, setDays] = useState(7)

  useEffect(() => {
    api.stats(days).then(setData).catch((e: any) => onErr(String(e.message ?? e)))
  }, [days])

  if (!data) return <p>Загрузка…</p>

  return (
    <div>
      <h2 style={s.h}>{data.rank?.emoji} {data.rank?.name}</h2>
      <p style={s.sub}>✨ {data.rank?.total_sparks} искр · 🔥 {data.streak} дней · 🏋️ {data.workout?.current_count}/{data.workout?.monthly_goal}</p>
      <div style={s.row}>
        {[7, 14, 30].map((d) => (
          <button key={d} onClick={() => setDays(d)} style={days === d ? s.btnActive : s.btnSm}>{d} дней</button>
        ))}
      </div>
      {(data.daily ?? []).map((d: any) => (
        <div key={d.date} style={s.card}>
          <div style={s.row}><b>{d.date}</b><span>{Object.entries(d.ratings).map(([k, v]) => `${SHORT[k] ?? k}${v}`).join(' ')}</span></div>
        </div>
      ))}
      {(data.daily ?? []).length === 0 && <p style={s.sub}>Пока нет оценок за период.</p>}
    </div>
  )
}
