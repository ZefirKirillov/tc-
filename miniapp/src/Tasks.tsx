import { useEffect, useState } from 'react'
import { api, haptic, notifyOk } from './api'
import { s } from './styles'
import { Confirm, Skeletons, useBanner } from './ui'

type Task = { id: number; title: string; is_priority: boolean; deadline: string | null; repeat_days: string | null; is_done: boolean }

const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export default function Tasks() {
  const b = useBanner()
  const [tasks, setTasks] = useState<Task[] | null>(null)
  const [title, setTitle] = useState('')
  const [prio, setPrio] = useState(false)
  const [deadline, setDeadline] = useState('')
  const [repeat, setRepeat] = useState<Set<number>>(new Set())
  const [delId, setDelId] = useState<number | null>(null)

  async function load() {
    try { setTasks(await api.tasks()) } catch (e) { b.setErr(e) }
  }
  useEffect(() => { load() }, [])

  async function add() {
    if (!title.trim()) { b.setErr('Назови задачу, даже коротко 🌠'); return }
    try {
      await api.addTask(title.trim(), prio, deadline || null, repeat.size ? [...repeat] : null)
      setTitle(''); setPrio(false); setDeadline(''); setRepeat(new Set())
      haptic(); notifyOk()
      await load()
    } catch (e) { b.setErr(e) }
  }

  async function done(id: number) {
    try { await api.doneTask(id); haptic(); notifyOk(); await load() }
    catch (e) { b.setErr(e) }
  }

  async function del() {
    if (delId == null) return
    setDelId(null)
    try { await api.deleteTask(delId); haptic(); await load() }
    catch (e) { b.setErr(e) }
  }

  function toggleDay(d: number) {
    const n = new Set(repeat)
    n.has(d) ? n.delete(d) : n.add(d)
    setRepeat(n)
  }

  if (!tasks) return <div><h2 style={s.h}>📝 Задачи</h2><Skeletons /></div>

  return (
    <div>
      <h2 style={s.h}>📝 Орбита задач</h2>
      {b.BannerEl}
      <div style={s.card}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Новая миссия…"
          style={s.input} maxLength={200} />
        <div style={{ ...s.row, marginTop: 8 }}>
          <label><input type="checkbox" checked={prio} onChange={(e) => setPrio(e.target.checked)} /> 🔥 Приоритет</label>
          <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} style={s.inputSm} />
        </div>
        <div style={{ ...s.row, marginTop: 4 }}>
          <span style={s.sub}>🔁 Повтор:</span>
          <div style={s.btns}>{WD.map((w, i) => (
            <button key={i} onClick={() => toggleDay(i)} style={repeat.has(i) ? s.btnActive : s.btn}>{w}</button>
          ))}</div>
        </div>
        <div style={{ marginTop: 8 }}><button onClick={add} style={s.primary}>🚀 Запустить</button></div>
      </div>
      {tasks.length === 0 && <p style={s.sub}>Орбита пуста. Запусти первую миссию! 🛸</p>}
      {tasks.map((t) => (
        <div key={t.id} style={{ ...s.card, opacity: t.is_done ? 0.55 : 1 }}>
          <div style={s.row}>
            <span>{t.is_priority ? '🔥 ' : ''}{t.title}</span>
          </div>
          <div style={s.sub}>
            {[t.deadline && `⏰ ${t.deadline}`,
              t.repeat_days && `🔁 ${t.repeat_days.split(',').map((d) => WD[parseInt(d)] ?? d).join(' ')}`]
              .filter(Boolean).join(' · ')}
          </div>
          <div style={{ ...s.row, marginTop: 8, marginBottom: 0 }}>
            {!t.is_done
              ? <button onClick={() => done(t.id)} style={s.primary}>✅ Готово</button>
              : <span style={s.sub}>✅ Выполнена</span>}
            <button onClick={() => setDelId(t.id)} style={s.danger}>🗑</button>
          </div>
        </div>
      ))}
      {delId != null && (
        <Confirm title="Удалить задачу?" body="Она исчезнет из орбиты навсегда 🕳️"
          okLabel="🗑 Удалить" onOk={del} onCancel={() => setDelId(null)} />
      )}
    </div>
  )
}
