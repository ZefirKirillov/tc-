import { useEffect, useState } from 'react'
import { api } from './api'
import { s } from './styles'

type Task = { id: number; title: string; is_priority: boolean; deadline: string | null; repeat_days: string | null; is_done: boolean }

export default function Tasks({ onErr }: { onErr: (e: string) => void }) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [title, setTitle] = useState('')
  const [prio, setPrio] = useState(false)
  const [deadline, setDeadline] = useState('')

  async function load() {
    try { setTasks(await api.tasks()) } catch (e: any) { onErr(String(e.message ?? e)) }
  }
  useEffect(() => { load() }, [])

  async function add() {
    if (!title.trim()) return
    try {
      await api.addTask(title.trim(), prio, deadline || null, null)
      setTitle(''); setPrio(false); setDeadline('')
      await load()
    } catch (e: any) { onErr(String(e.message ?? e)) }
  }

  async function done(id: number) {
    try { await api.doneTask(id); await load() } catch (e: any) { onErr(String(e.message ?? e)) }
  }

  async function del(id: number) {
    try { await api.deleteTask(id); await load() } catch (e: any) { onErr(String(e.message ?? e)) }
  }

  return (
    <div>
      <h2 style={s.h}>📝 Задачи</h2>
      <div style={s.card}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Новая задача…"
          style={s.input} maxLength={200} />
        <div style={{ ...s.row, marginTop: 8 }}>
          <label><input type="checkbox" checked={prio} onChange={(e) => setPrio(e.target.checked)} /> 🔥 Приоритет</label>
          <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} style={s.inputSm} />
        </div>
        <button onClick={add} style={s.primary}>Добавить</button>
      </div>
      {tasks.length === 0 && <p style={s.sub}>Задач пока нет. Добавь первую!</p>}
      {tasks.map((t) => (
        <div key={t.id} style={{ ...s.card, opacity: t.is_done ? 0.55 : 1 }}>
          <div style={s.row}>
            <span>{t.is_priority ? '🔥 ' : ''}{t.title}</span>
          </div>
          {t.deadline && <div style={s.sub}>⏰ {t.deadline}{t.repeat_days ? ` · 🔁 ${t.repeat_days}` : ''}</div>}
          <div style={{ ...s.row, marginTop: 8 }}>
            {!t.is_done
              ? <button onClick={() => done(t.id)} style={s.primary}>✅ Готово</button>
              : <span style={s.sub}>✅ Выполнена</span>}
            <button onClick={() => del(t.id)} style={s.danger}>🗑</button>
          </div>
        </div>
      ))}
    </div>
  )
}
