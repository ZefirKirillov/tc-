import { useEffect, useState } from 'react'
import { api } from './api'
import { Ico } from './icons'
import MainAction from './MainAction'
import { haptic, hapticSelect, inTelegram, notifyOk, useBackButton, type MainCfg } from './tg'
import { Confirm, Empty, fmt, fmtDate, fmtWeight, LoadError, Section, Skeleton, Skeletons, useBanner } from './ui'

function exName(ex: any) {
  return ex.exercise ?? ex.name ?? '?'
}

function target(ex: any) {
  const w = fmtWeight(ex.weight)
  return `${ex.sets ?? '?'}×${ex.reps ?? '?'}${w ? ` · ${w}` : ''}`
}

function resultText(r: any) {
  if (!r) return ''
  const w = fmtWeight(r.weight_done)
  return `${r.sets_done ?? '?'}×${r.reps_done ?? '?'}${w ? ` · ${w}` : ''}`
}

const DAYS: Array<[string, string]> = [
  ['monday', 'Понедельник'], ['tuesday', 'Вторник'], ['wednesday', 'Среда'], ['thursday', 'Четверг'],
  ['friday', 'Пятница'], ['saturday', 'Суббота'], ['sunday', 'Воскресенье'],
]

const SESSION_STATUS: Record<string, string> = { done: 'завершена', in_progress: 'в процессе', started: 'начата' }

function PlanPreview({ plan }: { plan: any }) {
  const week = plan?.week_1 ?? plan
  const days = DAYS.filter(([k]) => Array.isArray(week?.[k]) && week[k].length)
  const cycle = plan?.cycle_weeks
  if (!days.length) {
    // Unknown shape — show raw so the user can still judge before saving.
    return <pre className="answer" style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{JSON.stringify(week, null, 1).slice(0, 1500)}</pre>
  }
  return (
    <div>
      <div className="label" style={{ marginBottom: 10 }}>
        Неделя 1{cycle > 1 ? ` из ${cycle}` : ''} · {days.length} дн.
      </div>
      {days.map(([k, label]) => (
        <div key={k} className="plan-day">
          <div style={{ fontWeight: 600, marginBottom: 6 }}>{label}</div>
          <div className="rows">
            {week[k].map((ex: any, i: number) => (
              <div key={i} className="row" style={{ minHeight: 40, padding: '8px 12px' }}>
                <span className="wrap grow">{exName(ex)}</span>
                <span className="num muted" style={{ fontSize: 13, flex: 'none' }}>{target(ex)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

type Wiz = { step: number; goal: string; level: string; days: number; notes: string; plan: any; manual: string }
const NEW_WIZ: Wiz = { step: 0, goal: '', level: '', days: 3, notes: '', plan: null, manual: '' }

export default function Workout() {
  const b = useBanner()
  const [data, setData] = useState<any>(null)
  const [loadErr, setLoadErr] = useState<unknown>(null)
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [idx, setIdx] = useState(0)
  const [busy, setBusy] = useState(false)
  const [hist, setHist] = useState<any[] | null>(null)
  const [showHist, setShowHist] = useState(false)
  const [wiz, setWiz] = useState<Wiz | null>(null)
  const [txt, setTxt] = useState('')
  const [confirmFinish, setConfirmFinish] = useState(false)
  const [review, setReview] = useState<any>(null)
  const [reviewBusy, setReviewBusy] = useState(false)
  const [accepted, setAccepted] = useState<Set<number>>(new Set())

  async function load() {
    try {
      const d = await api.workout()
      setData(d)
      setLoadErr(null)
      const logged = new Set((d.logs ?? []).map((x: any) => x.exercise_name))
      const exs: any[] = d.today_exercises ?? []
      let i = exs.findIndex((e) => !logged.has(exName(e)))
      if (i === -1) i = exs.length
      setIdx(i)
      setSessionId(d.session?.id ?? null)
    } catch (e) {
      if (data) b.setErr(e)
      else setLoadErr(e)
    }
  }
  useEffect(() => { load() }, [])

  async function start() {
    setBusy(true)
    try {
      const r = await api.workoutStart()
      setSessionId(r.session_id)
      haptic('medium')
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function log(action: 'done' | 'skip') {
    const exs: any[] = data?.today_exercises ?? []
    if (!sessionId || idx >= exs.length) return
    setBusy(true)
    try {
      await api.workoutLog(sessionId, exs[idx], action)
      haptic()
      setIdx(idx + 1)
      setData(await api.workout())
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function logText() {
    const exs: any[] = data?.today_exercises ?? []
    if (!sessionId || idx >= exs.length || !txt.trim()) return
    setBusy(true)
    try {
      const r = await api.workoutLogText(sessionId, exs[idx], txt.trim())
      haptic()
      b.setOk(`Записано: ${resultText(r.result)}`)
      setTxt('')
      setIdx(idx + 1)
      setData(await api.workout())
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function finish() {
    if (!sessionId) return
    setConfirmFinish(false)
    setBusy(true)
    try {
      const r = await api.workoutFinish(sessionId)
      notifyOk()
      const extra = [r.spark_awarded && '+1 искра', r.rank_up && 'новый ранг'].filter(Boolean).join(' · ')
      b.setOk(`Тренировка завершена. Выполнено: ${r.done}, пропущено: ${r.skipped}${extra ? ` · ${extra}` : ''}`,
        r.spark_awarded || r.rank_up ? 'event' : 'ok')
      setSessionId(null); setIdx(0)
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function toggleHistory() {
    if (showHist) { setShowHist(false); return }
    setShowHist(true)
    try { setHist(await api.workoutHistory()) }
    catch (e) { b.setErr(e); setShowHist(false) }
  }

  async function genPlan() {
    if (!wiz || !wiz.goal || !wiz.level) return
    setBusy(true)
    try {
      const r = await api.workoutGenerate(wiz.goal, wiz.level, wiz.days, wiz.notes)
      setWiz({ ...wiz, step: 5, plan: r.plan })
      haptic()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function parseManual() {
    if (!wiz || wiz.manual.trim().length < 10) { b.setErr('Вставь план текстом — хотя бы пару строк.'); return }
    setBusy(true)
    try {
      const r = await api.workoutParsePlan(wiz.manual)
      setWiz({ ...wiz, step: 5, plan: r.plan })
      haptic()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function savePlan() {
    if (!wiz?.plan) return
    setBusy(true)
    try {
      await api.workoutSavePlan(wiz.plan, wiz.manual ? 'manual' : 'ai', wiz.goal, wiz.level, wiz.days)
      setWiz(null)
      notifyOk()
      b.setOk('План сохранён.')
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function loadReview() {
    setReviewBusy(true)
    try {
      const r = await api.workoutReview()
      setReview(r)
      setAccepted(new Set((r.changes ?? []).map((_: any, i: number) => i)))
    } catch (e) { b.setErr(e) } finally { setReviewBusy(false) }
  }

  async function applyReview() {
    if (!review?.changes) return
    const acc = review.changes.filter((_: any, i: number) => accepted.has(i))
    if (!acc.length) { b.setErr('Выбери хотя бы одну замену.'); return }
    setBusy(true)
    try {
      const r = await api.workoutApplyReview(acc)
      setReview(null)
      notifyOk()
      b.setOk(`Применено замен: ${r.applied}`)
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  // ---- derived view state (hooks below must run on every render) ----
  const inWizard = !!data && (!data.has_plan || !!wiz)
  const w: Wiz = wiz ?? NEW_WIZ
  const set = (p: Partial<Wiz>) => setWiz({ ...w, ...p })
  const exs: any[] = data?.today_exercises ?? []
  const restDay = !!data?.is_rest_day
  const active = !!data && !inWizard && !restDay && !!sessionId
  const allMarked = active && idx >= exs.length

  function wizBack() {
    hapticSelect()
    if (w.step === 5) set({ step: w.manual ? 4 : 3 })
    else if (w.step === 4) set({ step: 0, manual: '' })
    else if (w.step > 1) set({ step: w.step - 1 })
    else if (data?.has_plan) setWiz(null)
    else set({ step: 0 })
  }

  let backHandler: (() => void) | null = null
  if (inWizard && (w.step > 0 || data?.has_plan)) backHandler = wizBack
  else if (review) backHandler = () => setReview(null)
  else if (showHist) backHandler = () => setShowHist(false)
  useBackButton(backHandler, 1)

  let main: MainCfg = null
  if (confirmFinish || !data) main = null
  else if (inWizard) {
    if (w.step === 3) main = { text: 'Сгенерировать план', onClick: genPlan, busy, disabled: !w.goal || !w.level }
    else if (w.step === 4) main = { text: 'Разобрать план', onClick: parseManual, busy, disabled: w.manual.trim().length < 10 }
    else if (w.step === 5 && w.plan) main = { text: 'Сохранить план', onClick: savePlan, busy }
  } else if (!restDay && !sessionId && exs.length) {
    main = { text: `Начать тренировку · ${exs.length} упр.`, onClick: start, busy }
  } else if (active && !allMarked) {
    main = txt.trim()
      ? { text: 'Записать результат', onClick: logText, busy }
      : { text: 'Сделал по плану', onClick: () => log('done'), busy }
  } else if (allMarked) {
    main = { text: 'Завершить тренировку', onClick: () => setConfirmFinish(true), busy }
  }

  // ---- render ----

  if (!data) {
    if (loadErr) return <LoadError error={loadErr} onRetry={() => { setLoadErr(null); load() }} />
    return <div><Skeleton h={64} /><Skeletons n={4} h={52} /></div>
  }

  if (inWizard) {
    return (
      <div>
        {b.BannerEl}
        {w.step >= 1 && w.step <= 3 && (
          <div className="steps" aria-label={`Шаг ${w.step} из 3`}>
            {[1, 2, 3].map((i) => <i key={i} className={i <= w.step ? 'is-on' : ''} />)}
          </div>
        )}

        {w.step === 0 && (
          <Empty icon="dumbbell" title="Плана тренировок пока нет"
            text="Собери план с CheckAI за три шага или вставь свой текстом."
            action={
              <div className="btn-bar" style={{ width: '100%', maxWidth: 320 }}>
                <button onClick={() => { hapticSelect(); set({ step: 1 }) }} className="btn btn-primary">
                  <Ico.ai size={18} /> С CheckAI
                </button>
                <button onClick={() => { hapticSelect(); set({ step: 4 }) }} className="btn btn-ghost">
                  <Ico.pen size={18} /> Свой текст
                </button>
              </div>
            } />
        )}

        {w.step === 1 && (
          <Section label="Шаг 1 · цель">
            <div className="opts">{['Похудение', 'Набор массы', 'Сила', 'Выносливость'].map((g) => (
              <button key={g} onClick={() => { hapticSelect(); set({ goal: g, step: 2 }) }}
                className={`opt${w.goal === g ? ' is-on' : ''}`}>{g}</button>
            ))}</div>
          </Section>
        )}

        {w.step === 2 && (
          <Section label="Шаг 2 · уровень подготовки">
            <div className="opts">{['Новичок', 'Средний', 'Продвинутый'].map((l) => (
              <button key={l} onClick={() => { hapticSelect(); set({ level: l, step: 3 }) }}
                className={`opt${w.level === l ? ' is-on' : ''}`}>{l}</button>
            ))}</div>
          </Section>
        )}

        {w.step === 3 && (
          <Section label="Шаг 3 · дней в неделю" aux={<span className="num accent">{w.days}</span>}>
            <div className="chips" style={{ flexWrap: 'nowrap' }}>{[1, 2, 3, 4, 5, 6].map((d) => (
              <button key={d} onClick={() => { hapticSelect(); set({ days: d }) }}
                className={`chip num grow${w.days === d ? ' is-on' : ''}`} style={{ minHeight: 40 }}>{d}</button>
            ))}</div>
            <input value={w.notes} onChange={(e) => set({ notes: e.target.value })}
              placeholder="Пожелания: травмы, инвентарь…" className="field mt" maxLength={500} />
            <div className="row-meta mt">{w.goal} · {w.level}</div>
          </Section>
        )}

        {w.step === 4 && (
          <Section label="Свой план">
            <p className="muted" style={{ margin: '0 0 10px', fontSize: 14 }}>
              День недели с новой строки, под ним упражнения: <span className="num">Название — 3x8(80кг)</span>
            </p>
            <textarea value={w.manual} onChange={(e) => set({ manual: e.target.value })} className="field"
              placeholder={'Понедельник:\nЖим лёжа - 3x5(110кг)\nСреда:\nПрисед - 3x8(80кг)'} maxLength={20000} />
          </Section>
        )}

        {w.step === 5 && w.plan && (
          <Section label="План готов — проверь">
            <PlanPreview plan={w.plan} />
          </Section>
        )}

        {!inTelegram && backHandler && (
          <button onClick={wizBack} className="btn btn-quiet mt"><Ico.back size={16} /> Назад</button>
        )}
        <MainAction cfg={main} />
      </div>
    )
  }

  const logs: any[] = data.logs ?? []
  const logByName = new Map(logs.map((l) => [l.exercise_name, l]))
  const wp = data.week_progress

  return (
    <div>
      {b.BannerEl}

      <div className="hstack spread" style={{ marginBottom: 6 }}>
        <span className="label">Неделя <span className="num accent">{fmt(wp?.done ?? 0)}/{fmt(wp?.goal ?? 0)}</span></span>
        {data.next && <span className="label clip">След.: {data.next.day}, {data.next.date}</span>}
      </div>

      {restDay && (
        <Empty icon="moon" title="Сегодня день отдыха"
          text={data.next ? `Следующая тренировка — ${data.next.day}, ${data.next.date}.` : 'Восстановление — тоже часть плана.'} />
      )}

      {!restDay && !sessionId && (
        <Section label={`Сегодня · ${exs.length} упр.`}>
          <div className="rows">
            {exs.map((e, i) => (
              <div key={i} className="row">
                <span className="row-idx num">{String(i + 1).padStart(2, '0')}</span>
                <span className="wrap grow">{exName(e)}</span>
                <span className="num muted" style={{ fontSize: 13, flex: 'none', maxWidth: '40%', textAlign: 'right' }}>{target(e)}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {active && (
        <>
          <div className="rail" aria-hidden="true">
            {exs.map((e, i) => {
              const st = logByName.get(exName(e))?.status
              const cls = st === 'done' ? 'is-done' : st === 'skipped' ? 'is-skip' : i === idx ? 'is-cur' : ''
              return <i key={i} className={`rail-node ${cls}`} />
            })}
          </div>

          {!allMarked ? (
            <div className="panel ex-now">
              <span className="label">Упражнение <span className="num">{String(idx + 1).padStart(2, '0')}/{String(exs.length).padStart(2, '0')}</span></span>
              <div className="ex-name wrap">{exName(exs[idx])}</div>
              <div className="target">
                <div className="target-cell"><span className="label">Подходы</span><span className="num">{exs[idx].sets ?? '—'}</span></div>
                <div className="target-cell"><span className="label">Повторы</span><span className="num">{exs[idx].reps ?? '—'}</span></div>
                {fmtWeight(exs[idx].weight) && (
                  <div className="target-cell"><span className="label">Вес</span><span className="num">{fmtWeight(exs[idx].weight)}</span></div>
                )}
              </div>
              <div className="field-row mt">
                <input value={txt} onChange={(e) => setTxt(e.target.value)} className="field"
                  placeholder="Факт: 80х5, 75х6…" maxLength={500} disabled={busy}
                  onKeyDown={(e) => { if (e.key === 'Enter' && txt.trim()) logText() }} />
                <button onClick={() => log('skip')} disabled={busy} className="btn btn-ghost" aria-label="Пропустить упражнение">
                  <Ico.skip size={16} /> Пропуск
                </button>
              </div>
              <div className="row-meta" style={{ marginTop: 6 }}>
                Пустое поле — записать по плану. Текст разберёт CheckAI.
              </div>
            </div>
          ) : (
            <Empty icon="flag" title="Все упражнения отмечены" text="Заверши сессию, чтобы засчитать тренировку и получить искру." />
          )}

          {logs.length > 0 && (
            <Section label="Сессия" aux={<span className="num muted" style={{ fontSize: 12 }}>{logs.length}/{exs.length}</span>}>
              <div className="rows">
                {exs.map((e, i) => {
                  const l = logByName.get(exName(e))
                  if (!l) return null
                  return (
                    <div key={i} className="row">
                      <span className="row-idx num">{String(i + 1).padStart(2, '0')}</span>
                      <span className="grow wrap" style={{ color: l.status === 'done' ? undefined : 'var(--text-2)' }}>{exName(e)}</span>
                      {l.status === 'done'
                        ? <span className="status-tag is-done">{resultText(l.result) || 'готово'}</span>
                        : <span className="status-tag is-skip">пропуск</span>}
                    </div>
                  )
                })}
              </div>
            </Section>
          )}
        </>
      )}

      <MainAction cfg={main} />

      <Section label="Инструменты">
        <div className="btn-bar">
          <button onClick={toggleHistory} className={`btn btn-ghost btn-sm${showHist ? ' is-on' : ''}`}>
            <Ico.history size={16} /> {showHist ? 'Скрыть историю' : 'История'}
          </button>
          <button onClick={() => (review ? setReview(null) : loadReview())} className="btn btn-ghost btn-sm" disabled={reviewBusy}>
            <Ico.repeat size={16} /> {reviewBusy ? 'Анализ…' : review ? 'Скрыть ревью' : 'Ревью месяца'}
          </button>
          <button onClick={() => { hapticSelect(); setWiz({ ...NEW_WIZ, step: 1 }) }} className="btn btn-ghost btn-sm">
            <Ico.refresh size={16} /> Новый план
          </button>
        </div>

        {showHist && (
          <div className="mt">
            {hist == null ? <Skeletons n={3} h={48} /> : hist.length === 0
              ? <Empty icon="history" title="Истории пока нет" text="Завершённые тренировки появятся здесь." />
              : (
                <div className="rows">
                  {hist.map((h, i) => (
                    <div key={i} className="row">
                      <span className="num" style={{ fontSize: 13, flex: 'none' }}>{fmtDate(h.date, true)}</span>
                      <span className={`grow label${h.status === 'done' ? ' accent' : ''}`}>{SESSION_STATUS[h.status] ?? h.status}</span>
                      <span className="num muted" style={{ fontSize: 13 }}>
                        <span className="accent">{h.done}</span> / {h.skipped} проп.
                      </span>
                    </div>
                  ))}
                </div>
              )}
          </div>
        )}

        {review && (
          <div className="mt">
            {review.no_changes_needed || !(review.changes ?? []).length
              ? <Empty icon="check" title="Менять ничего не нужно" text="План в порядке — продолжай в том же темпе." />
              : (
                <>
                  <div className="label" style={{ marginBottom: 8 }}>CheckAI предлагает замены</div>
                  <div className="rows">
                    {review.changes.map((ch: any, i: number) => {
                      const on = accepted.has(i)
                      const toggle = () => { hapticSelect(); const n = new Set(accepted); on ? n.delete(i) : n.add(i); setAccepted(n) }
                      return (
                        <div key={i} className="row" onClick={toggle} style={{ cursor: 'pointer', alignItems: 'flex-start' }}>
                          <button className={`check${on ? ' is-on' : ''}`} role="checkbox" aria-checked={on}
                            onClick={(e) => { e.stopPropagation(); toggle() }}><Ico.check size={16} /></button>
                          <div className="grow wrap">
                            <div><span className="muted">{ch.old_exercise}</span> → <b>{ch.new_exercise}</b></div>
                            <div className="row-meta">{ch.day} · {ch.reason}</div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  <button onClick={applyReview} disabled={busy || accepted.size === 0} className="btn btn-ghost btn-block mt">
                    Применить выбранные · {accepted.size}
                  </button>
                </>
              )}
          </div>
        )}
      </Section>

      {confirmFinish && (
        <Confirm title="Завершить тренировку?"
          body="Сессия отметится выполненной, засчитается в план недели и месяца."
          okLabel="Завершить" onOk={finish} onCancel={() => setConfirmFinish(false)} />
      )}
    </div>
  )
}
