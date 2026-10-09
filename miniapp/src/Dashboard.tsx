import { useEffect, useState } from 'react'
import { api, keep, peek } from './api'
import type { Tab } from './App'
import CheckIn, { CATS, MANUAL } from './CheckIn'
import { Ico } from './icons'
import { cloudGet, cloudSet, hapticSelect } from './tg'
import Tour from './Tour'
import { fmt, fmtDate, Meter, plural, Spinner, useBanner } from './ui'

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

// ---------- widgets ----------
// One edge/glow mechanism for every widget: `glow` 0..1 fades in a coloured edge with a
// soft halo (gold = earned, silver = done but neutral). Plain edge when glow is 0.

type Tone = 'gold' | 'silver'

function Widget({ tone = 'gold', glow = 0, className = '', onClick, children, tour, label }: {
  tone?: Tone; glow?: number; className?: string; onClick: () => void; children: React.ReactNode; tour?: string; label: string
}) {
  return (
    <button className={`widget is-${tone} ${className}`} data-tour={tour} aria-label={label}
      style={{ '--glow': Math.max(0, Math.min(1, glow)).toFixed(2) } as React.CSSProperties}
      onClick={() => { hapticSelect(); onClick() }}>
      {children}
    </button>
  )
}

/** Workout today: done → gold, rest day → silver, otherwise plain. */
function workoutState(w: any): { text: string; tone: Tone; glow: number } {
  if (!w) return { text: 'Загрузка…', tone: 'gold', glow: 0 }
  if (!w.has_plan) return { text: 'Нет плана', tone: 'gold', glow: 0 }
  const exs: any[] = w.today_exercises ?? []
  if (w.is_rest_day || exs.length === 0) return { text: 'День отдыха', tone: 'silver', glow: 1 }
  if (w.session?.status === 'done') return { text: 'Сделана', tone: 'gold', glow: 1 }
  if (w.session?.status === 'skipped') return { text: 'Пропущена', tone: 'gold', glow: 0 }
  if (w.session) return { text: `В процессе · ${(w.logs ?? []).length}/${exs.length}`, tone: 'gold', glow: 0 }
  return { text: 'Не сделана', tone: 'gold', glow: 0 }
}

/** 1 at the calorie goal, fading as you move away from it (overeating fades twice as fast). */
function dietCloseness(eaten: number, goal: number): number {
  if (goal <= 0 || eaten <= 0) return 0
  const r = eaten / goal
  return r <= 1 ? r : Math.max(0, 1 - (r - 1) * 2)
}

function Score({ value }: { value?: number }) {
  return value
    ? <div className="w-score num">{value}<small>/10</small></div>
    : <div className="w-score num muted">—</div>
}

function taskOrder(a: any, b: any): number {
  if (!!a.is_priority !== !!b.is_priority) return a.is_priority ? -1 : 1
  if (a.deadline && b.deadline) return a.deadline < b.deadline ? -1 : a.deadline > b.deadline ? 1 : 0
  if (a.deadline || b.deadline) return a.deadline ? -1 : 1
  return a.id - b.id
}

// ---------- screen ----------

export default function Dashboard({ me, setMe, go, openCheckin, askAI }: {
  me: any; setMe: any; go: (t: Tab) => void; openCheckin?: boolean; askAI: (question: string) => void
}) {
  const b = useBanner()
  // null = closed; number = open at that manual category (-1 = first unrated)
  const [checkin, setCheckin] = useState<number | null>(openCheckin ? -1 : null)
  const [tour, setTour] = useState(false)
  const [workout, setWorkout] = useState<any>(() => peek('workout') ?? null)
  const [tasks, setTasks] = useState<any[] | null>(() => peek('tasks') ?? null)
  const [question, setQuestion] = useState('')

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

  function submitQuestion(e?: React.FormEvent) {
    e?.preventDefault()
    const q = question.trim()
    if (q.length < 3) return
    hapticSelect()
    ;(document.activeElement as HTMLElement | null)?.blur()
    askAI(q)
  }

  const ratings = me.today_ratings ?? {}
  const rated = CATS.map(([k]) => (ratings[k] ?? 0) > 0)

  const wDone = me.workout?.current_count ?? 0
  const wGoal = me.workout?.monthly_goal ?? 0
  const dietOn = !!me.diet?.configured && (me.diet?.daily_goal ?? 0) > 0
  const kcal = Math.round(me.diet?.today_calories ?? 0)
  const kcalGoal = Math.round(me.diet?.daily_goal ?? 0)

  const streak = me.streak ?? 0
  const sparks = me.rank?.total_sparks ?? 0
  const nextTotal = me.rank?.next_total
  const maxRank = nextTotal == null || nextTotal <= sparks

  const ws = workoutState(workout)
  const near = dietOn ? dietCloseness(kcal, kcalGoal) : 0

  const allTasks = tasks ?? []
  const openTasks = allTasks.filter((t) => !t.is_done)
  const topTasks = [...openTasks].sort(taskOrder).slice(0, 3)
  const tasksDone = allTasks.length ? (allTasks.length - openTasks.length) / allTasks.length : 0

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

      <form className="ask" onSubmit={submitQuestion} data-tour="ask">
        <Ico.ai size={18} className="ask-icon" />
        <input className="ask-input" value={question} onChange={(e) => setQuestion(e.target.value)}
          placeholder="Спроси Check…" maxLength={2000} enterKeyHint="send" aria-label="Вопрос для Check" />
        <button type="submit" className="ask-send" disabled={question.trim().length < 3} aria-label="Спросить">
          <Ico.arrow size={18} />
        </button>
      </form>
      <button className="ask-link" onClick={() => go('ai')}>Открыть Check →</button>

      <div className="widgets" data-tour="today">
        <div className="w-wide ci-row" data-tour="checkin">
          {MANUAL.map(([k, label, icon], i) => {
            const v = ratings[k] ?? 0
            const Icon = Ico[icon]
            return (
              <div key={k} className="ci-cell">
                <Widget className="ci-circle" label={`${label}: ${v || 'не оценено'}`}
                  tone={v >= 7 ? 'gold' : 'silver'} glow={v ? 1 : 0} onClick={() => setCheckin(i)}>
                  {v ? <span className="num ci-num">{v}</span> : <Icon size={24} className="muted" />}
                </Widget>
                <span className="ci-label">{label}</span>
              </div>
            )
          })}
        </div>

        <Widget className="w-square" label="Тренировка" tone={ws.tone} glow={ws.glow} onClick={() => go('workout')}>
          <span className="w-title"><Ico.dumbbell size={16} /> Тренировка</span>
          <Score value={ratings['активность']} />
          <span className={`w-foot${ws.glow ? (ws.tone === 'silver' ? ' is-silver' : ' is-gold') : ''}`}>{ws.text}</span>
        </Widget>

        <Widget className="w-square" label="Питание" glow={near} onClick={() => go('diet')}>
          <span className="w-title"><Ico.food size={16} /> Питание</span>
          <Score value={ratings['еда']} />
          {dietOn ? (
            <span className="w-foot-block">
              <span className="w-bar" style={{ '--glow': near.toFixed(2) } as React.CSSProperties}>
                <i style={{ width: `${Math.min(100, kcalGoal ? (kcal / kcalGoal) * 100 : 0)}%` }} />
              </span>
              <span className="w-foot num">{fmt(kcal)} / {fmt(kcalGoal)}</span>
            </span>
          ) : <span className="w-foot">Задай норму</span>}
        </Widget>

        <Widget className="w-wide w-tasks" label="Задачи" glow={tasksDone} onClick={() => go('tasks')}>
          <span className="hstack spread" style={{ width: '100%' }}>
            <span className="w-title"><Ico.tasks size={16} /> Задачи</span>
            <span className="num muted" style={{ fontSize: 13 }}>
              {tasks == null ? '…' : allTasks.length === 0 ? '' : `${allTasks.length - openTasks.length}/${allTasks.length}`}
            </span>
          </span>
          {tasks == null ? <span className="muted hstack" style={{ gap: 8 }}><Spinner /> Загрузка…</span>
            : openTasks.length === 0 ? <span className="muted">{allTasks.length ? 'Всё сделано 🎉' : 'Задач пока нет'}</span>
            : (
              <span className="w-list">
                {topTasks.map((t) => (
                  <span key={t.id} className="w-task">
                    {t.is_priority ? <Ico.flame size={14} className="warm" /> : <i className="w-dot" />}
                    <span className="clip grow">{t.title}</span>
                    {t.deadline && <span className="num muted" style={{ fontSize: 12 }}>{fmtDate(t.deadline)}</span>}
                  </span>
                ))}
                {openTasks.length > 3 && <span className="muted" style={{ fontSize: 13 }}>и ещё {openTasks.length - 3}</span>}
              </span>
            )}
        </Widget>
      </div>

      <button className="link-quiet" onClick={() => setTour(true)}>Как пользоваться</button>

      {checkin !== null && (
        <CheckIn me={me} setMe={setMe} start={checkin >= 0 ? checkin : undefined}
          onClose={() => setCheckin(null)} onError={b.setErr}
          onSpark={() => { b.setOk('День отмечен — искра зажжена 🔥', 'event'); api.me().then(setMe).catch(() => {}) }} />
      )}
      {tour && <Tour onDone={endTour} />}
    </div>
  )
}
