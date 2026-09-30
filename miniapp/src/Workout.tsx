import { useEffect, useState } from 'react'
import { api } from './api'
import { s } from './styles'

function exName(ex: any) {
  return ex.exercise ?? ex.name ?? '?'
}

export default function Workout({ onErr }: { onErr: (e: string) => void }) {
  const [data, setData] = useState<any>(null)
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [idx, setIdx] = useState(0)
  const [busy, setBusy] = useState(false)
  const [hist, setHist] = useState<any[]>([])
  const [showHist, setShowHist] = useState(false)
  // plan wizard state
  const [wiz, setWiz] = useState<null | { step: number; goal: string; level: string; days: number; notes: string; plan: any }>(null)

  async function load() {
    try {
      const d = await api.workout()
      setData(d)
      const l = new Set((d.logs ?? []).map((x: any) => x.exercise_name))
      const exs: any[] = d.today_exercises ?? []
      setIdx(exs.findIndex((e) => !l.has(exName(e))))
      if (idx === -1) setIdx(exs.length)
      setSessionId(d.session?.id ?? null)
    } catch (e: any) { onErr(String(e.message ?? e)) }
  }
  useEffect(() => { load() }, [])

  async function start() {
    setBusy(true)
    try {
      const r = await api.workoutStart()
      setSessionId(r.session_id)
    } catch (e: any) { onErr(String(e.message ?? e)) } finally { setBusy(false) }
  }

  async function log(action: 'done' | 'skip') {
    const exs: any[] = data?.today_exercises ?? []
    if (!sessionId || idx >= exs.length) return
    setBusy(true)
    try {
      await api.workoutLog(sessionId, exs[idx], action)
      setIdx(idx + 1)
      const d = await api.workout()
      setData(d)
    } catch (e: any) { onErr(String(e.message ?? e)) } finally { setBusy(false) }
  }

  async function finish() {
    if (!sessionId) return
    setBusy(true)
    try {
      const r = await api.workoutFinish(sessionId)
      onErr('') // clear
      alert(`Готово! ✅ Выполнено: ${r.done}, пропущено: ${r.skipped}${r.spark_awarded ? ' · ✨ +искра' : ''}`)
      setSessionId(null); setIdx(0)
      await load()
    } catch (e: any) { onErr(String(e.message ?? e)) } finally { setBusy(false) }
  }

  async function showHistory() {
    try { setHist(await api.workoutHistory()); setShowHist(!showHist) }
    catch (e: any) { onErr(String(e.message ?? e)) }
  }

  async function genPlan() {
    if (!wiz || !wiz.goal || !wiz.level) return
    setBusy(true)
    try {
      const r = await api.workoutGenerate(wiz.goal, wiz.level, wiz.days, wiz.notes)
      setWiz({ ...wiz, step: 4, plan: r.plan })
    } catch (e: any) { onErr(String(e.message ?? e)) } finally { setBusy(false) }
  }

  async function savePlan() {
    if (!wiz?.plan) return
    setBusy(true)
    try {
      await api.workoutSavePlan(wiz.plan, 'ai', wiz.goal, wiz.level, wiz.days)
      setWiz(null)
      await load()
    } catch (e: any) { onErr(String(e.message ?? e)) } finally { setBusy(false) }
  }

  if (!data) return <p>Загрузка…</p>

  // ---- plan wizard ----
  if (!data.has_plan || wiz) {
    const w = wiz ?? { step: 0, goal: '', level: '', days: 3, notes: '', plan: null }
    return (
      <div>
        <h2 style={s.h}>🏋️ План тренировок</h2>
        {w.step === 0 && (
          <div style={s.card}>
            <p>Плана пока нет. Создать с помощью ИИ?</p>
            <button onClick={() => setWiz({ ...w, step: 1 })} style={s.primary}>Создать план</button>
          </div>
        )}
        {w.step === 1 && (
          <div style={s.card}>
            <p><b>Шаг 1/3:</b> цель?</p>
            {['Похудение', 'Набор массы', 'Сила', 'Выносливость'].map((g) => (
              <button key={g} onClick={() => setWiz({ ...w, goal: g, step: 2 })}
                style={w.goal === g ? s.btnActive : s.btnSm}>{g}</button>
            ))}
          </div>
        )}
        {w.step === 2 && (
          <div style={s.card}>
            <p><b>Шаг 2/3:</b> уровень?</p>
            {['Новичок', 'Средний', 'Продвинутый'].map((l) => (
              <button key={l} onClick={() => setWiz({ ...w, level: l, step: 3 })}
                style={w.level === l ? s.btnActive : s.btnSm}>{l}</button>
            ))}
          </div>
        )}
        {w.step === 3 && (
          <div style={s.card}>
            <p><b>Шаг 3/3:</b> дней в неделю: {w.days}</p>
            <div style={s.btns}>{[1,2,3,4,5,6].map((d) => (
              <button key={d} onClick={() => setWiz({ ...w, days: d })} style={w.days === d ? s.btnActive : s.btn}>{d}</button>
            ))}</div>
            <input value={w.notes} onChange={(e) => setWiz({ ...w, notes: e.target.value })}
              placeholder="Пожелания (травмы, инвентарь…)" style={{ ...s.input, marginTop: 8 }} maxLength={500} />
            <div style={{ marginTop: 8 }}><button onClick={genPlan} disabled={busy} style={s.primary}>
              {busy ? 'Генерация…' : 'Сгенерировать ✨'}</button></div>
          </div>
        )}
        {w.step === 4 && w.plan && (
          <div style={s.card}>
            <p><b>План готов!</b> Проверь первую неделю:</p>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{JSON.stringify(w.plan.week_1 ?? w.plan, null, 1).slice(0, 1500)}</pre>
            <div style={s.row}>
              <button onClick={savePlan} disabled={busy} style={s.primary}>✅ Сохранить</button>
              <button onClick={() => setWiz({ ...w, step: 3 })} style={s.btnSm}>↩ Назад</button>
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
      <p style={s.sub}>Неделя: {data.week_progress?.done}/{data.week_progress?.goal}
        {data.next ? ` · След.: ${data.next.day}, ${data.next.date}` : ''}</p>
      {data.is_rest_day && <div style={s.card}><p>😴 Сегодня отдых. {data.next ? `Следующая: ${data.next.day}, ${data.next.date}` : ''}</p></div>}
      {!data.is_rest_day && !sessionId && (
        <div style={s.card}>
          <p>Сегодня: {exs.length} упр.</p>
          {exs.map((e, i) => <div key={i} style={s.sub}>{i + 1}. {exName(e)} {e.sets}×{e.reps}{e.weight ? ` @ ${e.weight}кг` : ''}</div>)}
          <div style={{ marginTop: 8 }}><button onClick={start} disabled={busy} style={s.primary}>▶ Начать</button></div>
        </div>
      )}
      {!data.is_rest_day && sessionId && idx < exs.length && (
        <div style={s.card}>
          <p><b>Упражнение {idx + 1} из {exs.length}</b></p>
          <h3>{exName(exs[idx])}</h3>
          <p>Цель: {exs[idx].sets} × {exs[idx].reps}{exs[idx].weight ? ` @ ${exs[idx].weight} кг` : ''}</p>
          <div style={s.row}>
            <button onClick={() => log('done')} disabled={busy} style={s.primary}>✅ Сделал</button>
            <button onClick={() => log('skip')} disabled={busy} style={s.btnSm}>⏭ Пропустить</button>
          </div>
        </div>
      )}
      {!data.is_rest_day && sessionId && idx >= exs.length && (
        <div style={s.card}>
          <p>Все упражнения отмечены!</p>
          <button onClick={finish} disabled={busy} style={s.primary}>🏁 Завершить тренировку</button>
        </div>
      )}
      <div style={{ marginTop: 12 }}>
        <button onClick={showHistory} style={s.btnSm}>{showHist ? 'Скрыть историю' : '📜 История'}</button>
        {showHist && hist.map((h, i) => (
          <div key={i} style={s.card}><div style={s.row}>
            <span>{h.date} · {h.status === 'done' ? '✅' : h.status}</span>
            <span>✔{h.done} ⏭{h.skipped}</span>
          </div></div>
        ))}
      </div>
      <div style={{ marginTop: 12 }}>
        <button onClick={() => setWiz({ step: 1, goal: '', level: '', days: 3, notes: '', plan: null })} style={s.btnSm}>🔄 Новый план</button>
      </div>
    </div>
  )
}
