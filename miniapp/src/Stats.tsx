import { useEffect, useState } from 'react'
import { api, haptic } from './api'
import { s } from './styles'
import { Skeletons, useBanner } from './ui'

const SHORT: Record<string, string> = { 'сон': '😴', 'еда': '🍽', 'активность': '💪', 'зависание': '🎮', 'настрой': '🎯' }

export default function Stats() {
  const b = useBanner()
  const [data, setData] = useState<any>(null)
  const [days, setDays] = useState(7)

  useEffect(() => {
    setData(null)
    api.stats(days).then(setData).catch((e) => b.setErr(e))
  }, [days])

  return (
    <div>
      <h2 style={s.h}>📊 Статистика</h2>
      {b.BannerEl}
      <div style={{ ...s.row, marginTop: 8 }}>
        {[7, 14, 30].map((d) => (
          <button key={d} onClick={() => { setDays(d); haptic() }} style={days === d ? s.btnActive : s.btnSm}>{d} дней</button>
        ))}
      </div>
      {!data && <Skeletons />}
      {data && (
        <>
          <div style={s.card}>
            <div style={s.row}><b>{data.rank?.emoji} {data.rank?.name}</b><span>✨ {data.rank?.total_sparks}</span></div>
            <div style={s.sub}>🔥 {data.streak} дней · 🏋️ {data.workout?.current_count}/{data.workout?.monthly_goal}</div>
          </div>
          {(data.daily ?? []).map((d: any) => (
            <div key={d.date} style={s.card}>
              <div style={s.row}><b>{d.date}</b><span>{Object.entries(d.ratings).map(([k, v]) => `${SHORT[k] ?? k}${v}`).join(' ')}</span></div>
            </div>
          ))}
          {(data.daily ?? []).length === 0 && <p style={s.sub}>Пока нет оценок за период.</p>}
        </>
      )}
    </div>
  )
}
