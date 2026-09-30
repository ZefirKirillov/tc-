import { useEffect, useState } from 'react'
import { api, haptic, notifyOk } from './api'
import { s } from './styles'
import { Confirm, Skeletons, useBanner } from './ui'

function exName(ex: any) {
  return ex.exercise ?? ex.name ?? '?'
}

type Wiz = { step: number; goal: string; level: string; days: number; notes: string; plan: any; manual: string }

export default function Workout() {
  const b = useBanner()
  const [data, setData] = useState<any>(null)
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [idx, setIdx] = useState(0)
  const [busy, setBusy] = useState(false)
  const [hist, setHist] = useState<any[]>([])
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
      const logged = new Set((d.logs ?? []).map((x: any) => x.exercise_name))
      const exs: any[] = d.today_exercises ?? []
      let i = exs.findIndex((e) => !logged.has(exName(e)))
      if (i === -1) i = exs.length
      setIdx(i)
      setSessionId(d.session?.id ?? null)
    } catch (e) { b.setErr(e) }
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
      b.setOk(`Записано: ${r.result?.sets_done ?? ''}×${r.result?.reps_done ?? ''}${r.result?.weight_done ? ` @ ${r.result.weight_done}` : ''} ✨`)
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
      b.setOk(`Миссия выполнена! 🛸 ✔${r.done} ⏭${r.skipped}${r.spark_awarded ? ' · ✨ +искра' : ''}${r.rank_up ? ' · Ранг повышен!' : ''}`)
      setSessionId(null); setIdx(0)
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function showHistory() {
    try { setHist(await api.workoutHistory()); setShowHist(!showHist) }
    catch (e) { b.setErr(e) }
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
    if (!wiz || wiz.manual.trim().length < 10) { b.setErr('Вставь план текстом — хотя бы пару строк 📝'); return }
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
      b.setOk('План сохранён в звёздную карту 🌌')
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
    if (!acc.length) { b.setErr('Выбери хотя бы одну замену 🌠'); return }
    setBusy(true)
    try {
      const r = await api.workoutApplyReview(acc)
      setReview(null)
      notifyOk()
      b.setOk(`Применено замен: ${r.applied} 🔄`)
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  if (!data) return <div><h2 style={s.h}>🏋️ Тренировка</h2><Skeletons /></div>

  // ---- plan wizard ----
  if (!data.has_plan || wiz) {
    const w: Wiz = wiz ?? { step: 0, goal: '', level: '', days: 3, notes: '', plan: null, manual: '' }
    const set = (p: Partial<Wiz>) => setWiz({ ...w, ...p })
    return (
      <div>
        <h2 style={s.h}>🌌 Карта тренировок</h2>
        {b.BannerEl}
        {w.step === 0 && (
          <div style={s.card}>
            <p>Плана пока нет. Создать с помощью ИИ или вставить свой?</p>
            <div style={s.row}>
              <button onClick={() => set({ step: 1 })} style={s.primary}>✨ С ИИ</button>
              <button onClick={() => set({ step: 4 })} style={s.btnSm}>📝 Свой текст</button>
            </div>
          </div>
        )}
        {w.step === 1 && (
          <div style={s.card}>
            <p><b>Шаг 1/3:</b> цель полёта?</p>
            <div style={s.btns}>{['Похудение', 'Набор массы', 'Сила', 'Выносливость'].map((g) => (
              <button key={g} onClick={() => { set({ goal: g, step: 2 }); haptic() }}
                style={w.goal === g ? s.btnActive : s.btnSm}>{g}</button>
            ))}</div>
          </div>
        )}
        {w.step === 2 && (
          <div style={s.card}>
            <p><b>Шаг 2/3:</b> уровень подготовки?</p>
            <div style={s.btns}>{['Новичок', 'Средний', 'Продвинутый'].map((l) => (
              <button key={l} onClick={() => { set({ level: l, step: 3 }); haptic() }}
                style={w.level === l ? s.btnActive : s.btnSm}>{l}</button>
            ))}</div>
          </div>
        )}
        {w.step === 3 && (
          <div style={s.card}>
            <p><b>Шаг 3/3:</b> дней в неделю: {w.days}</p>
            <div style={s.btns}>{[1,2,3,4,5,6].map((d) => (
              <button key={d} onClick={() => set({ days: d })} style={w.days === d ? s.btnActive : s.btn}>{d}</button>
            ))}</div>
            <input value={w.notes} onChange={(e) => set({ notes: e.target.value })}
              placeholder="Пожелания (травмы, инвентарь…)" style={{ ...s.input, marginTop: 8 }} maxLength={500} />
            <div style={{ marginTop: 8 }}><button onClick={genPlan} disabled={busy} style={s.primary}>
              {busy ? '🌌 Консультируюсь со звёздами…' : 'Сгенерировать ✨'}</button></div>
          </div>
        )}
        {w.step === 4 && (
          <div style={s.card}>
            <p><b>Свой план:</b> вставь текст в формате<br />День недели:<br />Название — СетыxПовторения(Вес)</p>
            <textarea value={w.manual} onChange={(e) => set({ manual: e.target.value })}
              placeholder={'Понедельник:\nЖим лёжа - 3x5(110кг)\nСреда:\nПрисед - 3x8(80кг)'} style={s.textarea} maxLength={20000} />
            <div style={{ ...s.row, marginTop: 8, marginBottom: 0 }}>
              <button onClick={() => set({ step: 0 })} style={s.btnSm}>↩ Назад</button>
              <button onClick={parseManual} disabled={busy} style={s.primary}>
                {busy ? '🌌 Разбираю…' : 'Разобрать ✨'}</button>
            </div>
          </div>
        )}
        {w.step === 5 && w.plan && (
          <div style={s.card}>
            <p><b>План готов!</b> Первая неделя:</p>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: '#d9ccff' }}>{JSON.stringify(w.plan.week_1 ?? w.plan, null, 1).slice(0, 1500)}</pre>
            <div style={s.row}>
              <button onClick={savePlan} disabled={busy} style={s.primary}>✅ Сохранить</button>
              <button onClick={() => set({ step: w.manual ? 4 : 3 })} style={s.btnSm}>↩ Назад</button>
            </div>
          </div>
        )}
      </div>
    )
  }

  // ---- today ----
  const exs: any[] = data.today_exercises ?? []
  return (
    <div>
      <h2 style={s.h}>🏋️ Тренировка</h2>
      {b.BannerEl}
      <p style={s.sub}>🪐 Неделя: {data.week_progress?.done}/{data.week_progress?.goal}
        {data.next ? ` · След.: ${data.next.day}, ${data.next.date}` : ''}</p>
      {data.is_rest_day && <div style={s.card}><p>🌙 Сегодня отдых — звёзды восстанавливаются. {data.next ? `Следующая: ${data.next.day}, ${data.next.date}` : ''}</p></div>}
      {!data.is_rest_day && !sessionId && (
        <div style={s.card}>
          <p>Сегодня: {exs.length} упр.</p>
          {exs.map((e, i) => <div key={i} style={s.sub}>{i + 1}. {exName(e)} {e.sets}×{e.reps}{e.weight ? ` @ ${e.weight}кг` : ''}</div>)}
          <div style={{ marginTop: 8 }}><button onClick={start} disabled={busy} style={s.primary}>▶ Начать миссию</button></div>
        </div>
      )}
      {!data.is_rest_day && sessionId && idx < exs.length && (
        <div style={s.card}>
          <p><b>Упражнение {idx + 1} из {exs.length}</b></p>
          <h3 style={{ margin: '4px 0' }}>{exName(exs[idx])}</h3>
          <p style={s.sub}>Цель: {exs[idx].sets} × {exs[idx].reps}{exs[idx].weight ? ` @ ${exs[idx].weight} кг` : ''}</p>
          <div style={s.row}>
            <button onClick={() => log('done')} disabled={busy} style={s.primary}>✅ Сделал</button>
            <button onClick={() => log('skip')} disabled={busy} style={s.btnSm}>⏭ Пропустить</button>
          </div>
          <input value={txt} onChange={(e) => setTxt(e.target.value)}
            placeholder='Или напиши: "жим 80х5, тяжело"' style={s.input} maxLength={500} />
          <div style={{ marginTop: 8 }}>
            <button onClick={logText} disabled={busy || !txt.trim()} style={s.btnSm}>
              {busy ? '🌌…' : '✍️ Записать текстом'}
            </button>
          </div>
        </div>
      )}
      {!data.is_rest_day && sessionId && idx >= exs.length && (
        <div style={s.card}>
          <p>Все упражнения отмечены! 🎉</p>
          <button onClick={() => setConfirmFinish(true)} disabled={busy} style={s.primary}>🏁 Завершить тренировку</button>
        </div>
      )}
      {confirmFinish && (
        <Confirm title="Завершить тренировку?"
          body="Сессия отметится выполненной, зажжётся искра ✨"
          okLabel="🏁 Завершить" onOk={finish} onCancel={() => setConfirmFinish(false)} />
      )}
      <div style={{ marginTop: 12 }}>
        <button onClick={showHistory} style={s.btnSm}>{showHist ? 'Скрыть историю' : '📜 История'}</button>
        {' '}
        <button onClick={review ? () => setReview(null) : loadReview} style={s.btnSm} disabled={reviewBusy}>
          {reviewBusy ? '🌌 Анализ…' : review ? 'Скрыть ревью' : '🔄 Месячное ревью'}
        </button>
        {showHist && hist.map((h, i) => (
          <div key={i} style={s.card}><div style={s.row}>
            <span>{h.date} · {h.status === 'done' ? '✅' : h.status}</span>
            <span>✔{h.done} ⏭{h.skipped}</span>
          </div></div>
        ))}
        {review && (
          <div style={s.card}>
            {review.no_changes_needed || !(review.changes ?? []).length
              ? <p>✨ Космос доволен — менять ничего не нужно!</p>
              : <>
                <p><b>ИИ предлагает замены:</b> выбери какие применить:</p>
                {review.changes.map((ch: any, i: number) => (
                  <label key={i} style={{ display: 'block', padding: '6px 0', borderTop: '1px solid rgba(150,110,255,0.2)' }}>
                    <input type="checkbox" checked={accepted.has(i)}
                      onChange={() => { const n = new Set(accepted); n.has(i) ? n.delete(i) : n.add(i); setAccepted(n) }} />
                    {' '}{ch.old_exercise} → <b>{ch.new_exercise}</b>
                    <div style={s.sub}>{ch.day} · {ch.reason}</div>
                  </label>
                ))}
                <button onClick={applyReview} disabled={busy} style={s.primary}>Применить выбранные 🔄</button>
              </>}
          </div>
        )}
      </div>
      <div style={{ marginTop: 12 }}>
        <button onClick={() => setWiz({ step: 1, goal: '', level: '', days: 3, notes: '', plan: null, manual: '' })} style={s.btnSm}>🔄 Новый план</button>
      </div>
    </div>
  )
}
