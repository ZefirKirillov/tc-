import { useEffect, useState } from 'react'
import { api, keep, peek } from './api'
import type { Tab } from './App'
import CheckIn, { CATS, MANUAL } from './CheckIn'
import { Ico, type IconName } from './icons'
import { cloudGet, cloudSet, hapticSelect } from './tg'
import Tour from './Tour'
import { fmt, Meter, plural, Section, useBanner } from './ui'

const TOUR_KEY = 'tc_tour_v1'

// ---------- orbital status instrument ----------

const SIZE = 132
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
  const r1 = 59, w1 = 7
  const c1 = 2 * Math.PI * r1
  const seg = (64 / 360) * c1 // 5 segments × 72°, 8° gaps
  const allRated = rated.every(Boolean)
  return (
    <svg className="orbit" viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
      aria-label={`Чек-ин ${rated.filter(Boolean).length} из 5, серия ${streak} дней`}>
      {rated.map((on, i) => (
        <circle key={i} className="orbit-arc" cx={C0} cy={C0} r={r1} strokeWidth={w1}
          stroke={on ? (allRated ? 'var(--warm)' : 'var(--accent)') : 'var(--surface-2)'}
          strokeDasharray={`${seg} ${c1}`} strokeLinecap="butt"
          transform={`rotate(${-90 + i * 72 + 4} ${C0} ${C0})`} />
      ))}
      <Ring r={48} w={5} p={workouts} color={workouts >= 1 ? 'var(--warm)' : 'var(--metal)'} />
      {kcal != null
        ? <Ring r={39} w={5} p={kcal} color={kcal > 1.1 ? 'var(--danger)' : 'var(--accent-dim)'} />
        : <circle cx={C0} cy={C0} r={39} fill="none" stroke="var(--line-strong)" strokeWidth={1} strokeDasharray="2 4" />}
      <g transform={`translate(${C0 - 11} ${C0 - 13})`} style={{ color: streak > 0 ? 'var(--warm)' : 'var(--text-3)' }}>
        <path d="M11 24c4.2 0 7-2.8 7-6.8 0-4.9-4-7.2-5.1-11.9-2.3 1.6-3.9 4.2-3.6 7.2-1.2-.7-2-1.9-2.2-3.3C5.3 11 4 13.7 4 17.2 4 21.2 6.8 24 11 24z"
          fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round" />
      </g>
    </svg>
  )
}

// ---------- today list ----------

function workoutStatus(w: any): { sub: string; done: boolean } {
  if (!w) return { sub: 'Загрузка…', done: false }
  if (!w.has_plan) return { sub: 'Создай план — это пара минут', done: false }
  const exs: any[] = w.today_exercises ?? []
  if (w.is_rest_day || exs.length === 0) return { sub: 'Сегодня отдых', done: true }
  if (w.session?.status === 'done') return { sub: 'Готово', done: true }
  if (w.session) {
    const n = (w.logs ?? []).length
    return { sub: `В процессе · ${n} из ${exs.length}`, done: false }
  }
  return { sub: `${exs.length} ${plural(exs.length, 'упражнение', 'упражнения', 'упражнений')}`, done: false }
}

function Cell({ icon, tone, title, sub, done, onClick, tour }: {
  icon: IconName; tone?: 'metal' | 'warm'; title: string; sub: string; done?: boolean; onClick: () => void; tour?: string
}) {
  const Icon = Ico[icon]
  return (
    <button className="cell" onClick={() => { hapticSelect(); onClick() }} data-tour={tour}>
      <span className={`cell-icon${tone ? ` is-${tone}` : ''}`}><Icon size={20} /></span>
      <span className="grow">
        <span className="cell-title" style={{ display: 'block' }}>{title}</span>
        <span className="cell-sub clip" style={{ display: 'block' }}>{sub}</span>
      </span>
      {done ? <Ico.check size={20} className="cell-done" /> : <Ico.arrow size={16} className="cell-chev" />}
    </button>
  )
}

// ---------- screen ----------

export default function Dashboard({ me, setMe, go, openCheckin }: {
  me: any; setMe: any; go: (t: Tab) => void; openCheckin?: boolean
}) {
  const b = useBanner()
  const [checkin, setCheckin] = useState(!!openCheckin)
  const [tour, setTour] = useState(false)
  const [workout, setWorkout] = useState<any>(() => peek('workout') ?? null)
  const [tasks, setTasks] = useState<any[] | null>(() => peek('tasks') ?? null)

  useEffect(() => {
    api.workout().then((d) => setWorkout(keep('workout', d))).catch(() => {})
    api.tasks().then((t) => setTasks(keep('tasks', t))).catch(() => {})
    // First visit → tutorial (not on top of a deep-linked check-in).
    if (!openCheckin) cloudGet(TOUR_KEY).then((v) => { if (!v) setTour(true) })
  }, [])

  function endTour() {
    setTour(false)
    cloudSet(TOUR_KEY, '1')
  }

  const ratings = me.today_ratings ?? {}
  const rated = CATS.map(([k]) => (ratings[k] ?? 0) > 0)
  const ratedN = rated.filter(Boolean).length
  const manualN = MANUAL.filter(([k]) => (ratings[k] ?? 0) > 0).length

  const wDone = me.workout?.current_count ?? 0
  const wGoal = me.workout?.monthly_goal ?? 0
  const dietOn = !!me.diet?.configured && (me.diet?.daily_goal ?? 0) > 0
  const kcal = Math.round(me.diet?.today_calories ?? 0)
  const kcalGoal = Math.round(me.diet?.daily_goal ?? 0)

  const streak = me.streak ?? 0
  const sparks = me.rank?.total_sparks ?? 0
  const nextTotal = me.rank?.next_total
  const maxRank = nextTotal == null || nextTotal <= sparks

  const ws = workoutStatus(workout)
  const openTasks = tasks?.filter((t) => !t.is_done).length

  return (
    <div>
      {b.BannerEl}

      <div className="hero" data-tour="hero">
        <Orbit rated={rated} streak={streak}
          workouts={wGoal > 0 ? wDone / wGoal : 0}
          kcal={dietOn ? kcal / kcalGoal : null} />
        <div style={{ minWidth: 0 }}>
          <div className={`hero-streak num${streak > 0 ? ' warm' : ' muted'}`}>
            {fmt(streak)}<small>{plural(streak, 'день', 'дня', 'дней')} подряд</small>
          </div>
          <div className="rankline-top">
            <span className="wrap" style={{ fontWeight: 600, fontSize: 14 }}>{me.rank?.emoji} {me.rank?.name}</span>
          </div>
          <Meter value={sparks} max={maxRank ? sparks || 1 : nextTotal} tone="warm" />
          <div className="label" style={{ marginTop: 6 }}>
            {maxRank ? `${fmt(sparks)} искр · максимальный ранг` : `${fmt(sparks)} из ${fmt(nextTotal)} искр до ранга`}
          </div>
        </div>
      </div>

      <Section label="План на сегодня">
        <div className="cells" data-tour="today">
          <Cell tour="checkin" icon="target" title="Чек-ин дня"
            sub={ratedN === 5 ? 'Готово — искра зажжена'
              : manualN === MANUAL.length ? 'Готово'
              : manualN === 0 ? `${MANUAL.length} оценки · минута` : `${manualN} из ${MANUAL.length}`}
            done={manualN === MANUAL.length} onClick={() => setCheckin(true)} />
          <Cell icon="dumbbell" tone="metal" title="Тренировка" sub={ws.sub} done={ws.done} onClick={() => go('workout')} />
          <Cell icon="food" title="Питание"
            sub={dietOn ? `${fmt(kcal)} из ${fmt(kcalGoal)} ккал` : 'Задай норму калорий'}
            onClick={() => go('diet')} />
          <Cell icon="tasks" title="Задачи"
            sub={openTasks == null ? 'Загрузка…' : tasks!.length === 0 ? 'Пока пусто' : openTasks === 0 ? 'Всё сделано' : `${openTasks} ${plural(openTasks, 'активная', 'активные', 'активных')}`}
            done={openTasks === 0 && (tasks?.length ?? 0) > 0} onClick={() => go('tasks')} />
          <Cell icon="ai" title="CheckAI" sub="Совет по твоим данным" onClick={() => go('ai')} />
        </div>
      </Section>

      <button className="link-quiet" onClick={() => setTour(true)}>Как пользоваться</button>

      {checkin && <CheckIn me={me} setMe={setMe} onClose={() => setCheckin(false)} onError={b.setErr} />}
      {tour && <Tour onDone={endTour} />}
    </div>
  )
}
