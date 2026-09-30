import { useState } from 'react'
import { api, haptic, notifyOk } from './api'
import { s } from './styles'
import { useBanner } from './ui'

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

export default function Dashboard({ me, setMe }: { me: any; setMe: any }) {
  const b = useBanner()
  const [pending, setPending] = useState<string | null>(null)

  async function rate(cat: string, val: number) {
    setPending(cat)
    try {
      const res = await api.saveRating(cat, val)
      setMe((m: any) => ({ ...m, today_ratings: res.ratings }))
      haptic()
      if (res.spark_awarded) {
        notifyOk()
        b.setOk('✨ Искра зажжена! Все категории заполнены 🌌')
      }
    } catch (e) {
      b.setErr(e)
    } finally {
      setPending(null)
    }
  }

  return (
    <div>
      <h2 style={s.h}>🌌 TrackCheck {me.rank?.emoji}</h2>
      {b.BannerEl}
      <p style={s.sub}>{me.rank?.name} · 🔥 {me.streak} дней · ✨ {me.rank?.total_sparks}/{me.rank?.next_total}</p>
      <p style={s.sub}>🏋️ {me.workout?.current_count}/{me.workout?.monthly_goal} · 🍽 {Math.round(me.diet?.today_calories ?? 0)}/{Math.round(me.diet?.daily_goal ?? 0)}</p>
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
