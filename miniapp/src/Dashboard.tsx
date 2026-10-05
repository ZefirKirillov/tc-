import { useState } from 'react'
import { api } from './api'
import type { Tab } from './App'
import { Ico, type IconName } from './icons'
import { haptic, notifyOk } from './tg'
import { fmt, Meter, Section, useBanner } from './ui'

const CATS: Array<[string, string, IconName]> = [
  ['сон', 'Сон', 'sleep'],
  ['еда', 'Еда', 'food'],
  ['активность', 'Активность', 'activity'],
  ['зависание', 'Зависание', 'idle'],
  ['настрой', 'Настрой', 'target'],
]

// ---------- orbital status instrument ----------

const SIZE = 148
const C0 = SIZE / 2

function Ring({ r, w, p, color }: { r: number; w: number; p: number; color: string }) {
  const c = 2 * Math.PI * r
  const len = Math.max(0, Math.min(1, p)) * c
  return (
    <>
      <circle className="orbit-track" cx={C0} cy={C0} r={r} strokeWidth={w} />
      {len > 0 && (
        <circle className="orbit-arc" cx={C0} cy={C0} r={r} strokeWidth={w} stroke={color}
          strokeDasharray={`${len} ${c}`} transform={`rotate(-90 ${C0} ${C0})`} />
      )}
    </>
  )
}

function Orbit({ rated, workouts, kcal, streak }: {
  rated: boolean[]; workouts: number; kcal: number | null; streak: number
}) {
  const r1 = 66, w1 = 7
  const c1 = 2 * Math.PI * r1
  const seg = (64 / 360) * c1 // 5 segments × 72°, 8° gaps
  const allRated = rated.every(Boolean)
  return (
    <svg className="orbit" viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
      aria-label={`Чек-ин ${rated.filter(Boolean).length} из 5, серия ${streak} дней`}>
      {[0, 90, 180, 270].map((a) => (
        <line key={a} className="orbit-tick" x1={C0} y1={1} x2={C0} y2={4} transform={`rotate(${a} ${C0} ${C0})`} />
      ))}
      {rated.map((on, i) => (
        <circle key={i} className="orbit-arc" cx={C0} cy={C0} r={r1} strokeWidth={w1}
          stroke={on ? (allRated ? 'var(--warm)' : 'var(--accent)') : 'var(--surface-2)'}
          strokeDasharray={`${seg} ${c1}`} strokeLinecap="butt"
          transform={`rotate(${-90 + i * 72 + 4} ${C0} ${C0})`} />
      ))}
      <Ring r={54} w={5} p={workouts} color={workouts >= 1 ? 'var(--warm)' : 'var(--metal)'} />
      {kcal != null
        ? <Ring r={44} w={5} p={kcal} color={kcal > 1.1 ? 'var(--danger)' : 'var(--accent-dim)'} />
        : <circle cx={C0} cy={C0} r={44} fill="none" stroke="var(--line-strong)" strokeWidth={1} strokeDasharray="2 4" />}
      <text x={C0} y={C0 + 4} textAnchor="middle" className="num"
        style={{ fontSize: streak > 999 ? 20 : 28, fontWeight: 600, fill: streak > 0 ? 'var(--warm)' : 'var(--text-3)' }}>
        {streak > 99999 ? '99k+' : streak}
      </text>
      <text x={C0} y={C0 + 20} textAnchor="middle" className="label" style={{ fill: 'var(--text-3)', fontSize: 9 }}>
        дн. серия
      </text>
    </svg>
  )
}

// ---------- screen ----------

export default function Dashboard({ me, setMe, go }: { me: any; setMe: any; go: (t: Tab) => void }) {
  const b = useBanner()
  const [pending, setPending] = useState<string | null>(null)

  async function rate(cat: string, val: number) {
    setPending(cat)
    haptic()
    try {
      const res = await api.saveRating(cat, val)
      setMe((m: any) => ({ ...m, today_ratings: res.ratings }))
      if (res.spark_awarded) {
        notifyOk()
        b.setOk('Искра зажжена — все категории дня заполнены.', 'event')
      }
    } catch (e) {
      b.setErr(e)
    } finally {
      setPending(null)
    }
  }

  const ratings = me.today_ratings ?? {}
  const rated = CATS.map(([k]) => (ratings[k] ?? 0) > 0)
  const ratedN = rated.filter(Boolean).length

  const wDone = me.workout?.current_count ?? 0
  const wGoal = me.workout?.monthly_goal ?? 0
  const dietOn = !!me.diet?.configured && (me.diet?.daily_goal ?? 0) > 0
  const kcal = me.diet?.today_calories ?? 0
  const kcalGoal = me.diet?.daily_goal ?? 0

  const sparks = me.rank?.total_sparks ?? 0
  const nextTotal = me.rank?.next_total
  const maxRank = nextTotal == null || nextTotal <= sparks

  return (
    <div>
      {b.BannerEl}

      <div className="station">
        <Orbit rated={rated} streak={me.streak ?? 0}
          workouts={wGoal > 0 ? wDone / wGoal : 0}
          kcal={dietOn ? kcal / kcalGoal : null} />
        <div className="readouts">
          <div className="readout">
            <div className="label"><i className="dot" style={{ background: ratedN === 5 ? 'var(--warm)' : 'var(--accent)' }} />Чек-ин</div>
            <div className="readout-val num">{ratedN}<small>/5</small></div>
          </div>
          <div className="readout">
            <div className="label"><i className="dot" style={{ background: wGoal > 0 && wDone >= wGoal ? 'var(--warm)' : 'var(--metal)' }} />Тренировки</div>
            <div className="readout-val num clip">{fmt(wDone)}<small>/{fmt(wGoal)}</small></div>
          </div>
          <div className="readout">
            <div className="label"><i className="dot" style={{ background: dietOn ? (kcalGoal > 0 && kcal / kcalGoal > 1.1 ? 'var(--danger)' : 'var(--accent-dim)') : 'var(--line-strong)' }} />Ккал</div>
            {dietOn
              ? <div className="readout-val num clip">{fmt(Math.round(kcal))}<small>/{fmt(Math.round(kcalGoal))}</small></div>
              : <div className="readout-val muted" style={{ fontSize: 13 }}>не настроено</div>}
          </div>
        </div>
      </div>

      <div className="rankline">
        <div className="rankline-top">
          <span className="wrap" style={{ fontWeight: 600 }}>{me.rank?.emoji} {me.rank?.name}</span>
          <span className="num warm" style={{ fontSize: 13, flex: 'none' }}>
            <Ico.spark size={13} /> {fmt(sparks)}{maxRank ? '' : <span className="muted">/{fmt(nextTotal)}</span>}
          </span>
        </div>
        <Meter value={sparks} max={maxRank ? sparks || 1 : nextTotal} tone="warm" />
      </div>

      <button className="cta" onClick={() => go('workout')}>
        <Ico.dumbbell size={22} className="cta-icon" />
        <span className="grow">
          <span style={{ fontWeight: 600, display: 'block' }}>Тренировка на сегодня</span>
          <span className="row-meta">Начать или отметить упражнения</span>
        </span>
        <Ico.arrow size={18} className="accent" />
      </button>

      <Section label="Чек-ин дня" aux={<span className={`num ${ratedN === 5 ? 'warm' : 'muted'}`} style={{ fontSize: 12 }}>{ratedN}/5</span>}>
        <div className="rows">
          {CATS.map(([key, label, icon]) => {
            const cur = ratings[key] ?? 0
            const Icon = Ico[icon]
            return (
              <div key={key} className="rate">
                <div className="rate-head">
                  <Icon size={18} />
                  <span className="grow">{label}</span>
                  <span className={`rate-val num${cur ? '' : ' is-empty'}`}>{cur || '–'}</span>
                </div>
                <div className={`scale${pending === key ? ' is-busy' : ''}`} role="radiogroup" aria-label={label}>
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((v) => (
                    <button key={v} role="radio" aria-checked={cur === v} aria-label={`${label}: ${v}`}
                      disabled={pending === key} onClick={() => rate(key, v)}
                      className={`scale-step${v === cur ? ' is-cur' : v < cur ? ' is-fill' : ''}`}>
                      {v}
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </Section>
    </div>
  )
}
