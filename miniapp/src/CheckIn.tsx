import { useState } from 'react'
import { api } from './api'
import { Ico, type IconName } from './icons'
import { haptic, hapticSelect, notifyOk } from './tg'
import { Sheet } from './ui'

export const CATS: Array<[string, string, IconName, string]> = [
  // key (API), label, icon, question — order matches the ring on "Сегодня"
  ['сон', 'Сон', 'sleep', 'Как спалось?'],
  ['еда', 'Еда', 'food', ''],
  ['активность', 'Активность', 'activity', ''],
  ['зависание', 'Зависание', 'idle', 'Удалось не залипать в телефон и игры?'],
  ['настрой', 'Настрой', 'target', 'Какой настрой?'],
]

// Еда and активность are scored by the server (calories vs goal, workout vs plan) — not rated by hand.
const AUTO = new Set(['еда', 'активность'])
export const MANUAL = CATS.filter(([k]) => !AUTO.has(k))
const AUTO_CATS = CATS.filter(([k]) => AUTO.has(k))

/** One category at a time, big targets, auto-advance to the next unrated one.
 *  Completing the day (spark awarded) shows a short celebration. */
export default function CheckIn({ me, setMe, onClose, onError, start }: {
  me: any; setMe: (f: (m: any) => any) => void; onClose: () => void; onError: (e: unknown) => void; start?: number
}) {
  const ratings: Record<string, number> = me.today_ratings ?? {}
  const firstOpen = MANUAL.findIndex(([k]) => !ratings[k])
  const [cur, setCur] = useState(start ?? (firstOpen === -1 ? 0 : firstOpen))
  const [busy, setBusy] = useState(false)
  const [spark, setSpark] = useState(false)

  const [key, label, icon, question] = MANUAL[cur]
  const Icon = Ico[icon]
  const value = ratings[key] ?? 0

  async function rate(v: number) {
    if (busy) return
    setBusy(true)
    haptic()
    try {
      const res = await api.saveRating(key, v)
      const merged: Record<string, number> = res.ratings ?? { ...ratings, [key]: v }
      setMe((m: any) => ({ ...m, today_ratings: merged }))
      if (res.spark_awarded) { notifyOk(); setSpark(true) }
      // next unrated category, searching forward from the current one (wrapping around)
      const order = MANUAL.map((_, i) => (cur + 1 + i) % MANUAL.length).filter((i) => i !== cur)
      const next = order.find((i) => !merged[MANUAL[i][0]]) ?? -1
      if (next !== -1) window.setTimeout(() => setCur(next), 220)
      else if (!res.spark_awarded) window.setTimeout(onClose, 450) // everything rated — get out of the way
    } catch (e) {
      onError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet onClose={onClose} aux={<button className="btn btn-quiet btn-sm" onClick={onClose}>Готово</button>}>
      <div className="ci-dots" role="tablist" aria-label="Категории">
        {MANUAL.map(([k, l, ic], i) => {
          const I = Ico[ic]
          return (
            <button key={k} role="tab" aria-selected={i === cur} aria-label={l}
              className={`ci-dot${ratings[k] ? ' is-rated' : ''}${i === cur ? ' is-cur' : ''}`}
              onClick={() => { hapticSelect(); setCur(i) }}>
              {ratings[k] ? <span className="num" style={{ fontSize: 13 }}>{ratings[k]}</span> : <I size={16} />}
            </button>
          )
        })}
      </div>

      {spark ? (
        <div className="ci-done">
          <Ico.spark size={34} />
          <h2 style={{ margin: '10px 0 4px' }}>День отмечен</h2>
          <p className="muted" style={{ margin: '0 0 18px' }}>Искра зажжена — серия продолжается 🔥</p>
          <button className="btn btn-primary btn-block" onClick={onClose}>Отлично</button>
        </div>
      ) : (
        <>
          <div className="ci-head">
            <Icon size={28} className="accent" />
            <h2>{label}</h2>
            <div className="muted">{question}</div>
          </div>
          <div className="ci-grid" role="radiogroup" aria-label={label} style={busy ? { opacity: 0.6 } : undefined}>
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((v) => (
              <button key={v} role="radio" aria-checked={value === v} disabled={busy}
                className={`ci-val${value === v ? ' is-on' : ''}`} onClick={() => rate(v)}>
                {v}
              </button>
            ))}
          </div>
          <div className="ci-scale"><span>плохо</span><span>отлично</span></div>
        </>
      )}

      <div className="ci-auto">
        {AUTO_CATS.map(([k, l, ic]) => {
          const I = Ico[ic]
          return (
            <div key={k} className="ci-auto-row">
              <I size={18} />
              <span className="grow">{l}</span>
              <span className={`num${ratings[k] ? '' : ' muted'}`}>{ratings[k] ? `${ratings[k]}/10` : '—'}</span>
            </div>
          )
        })}
      </div>
    </Sheet>
  )
}
