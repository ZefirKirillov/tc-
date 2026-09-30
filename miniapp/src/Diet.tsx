import { useEffect, useState } from 'react'
import { api } from './api'
import { s } from './styles'

export default function Diet({ onErr }: { onErr: (e: string) => void }) {
  const [data, setData] = useState<any>(null)
  const [desc, setDesc] = useState('')
  const [cal, setCal] = useState('')
  const [meal, setMeal] = useState('Еда')

  async function load() {
    try { setData(await api.diet()) } catch (e: any) { onErr(String(e.message ?? e)) }
  }
  useEffect(() => { load() }, [])

  async function log() {
    const calories = parseFloat(cal)
    if (!desc.trim() || !(calories > 0)) return
    try {
      await api.logFood(desc.trim(), calories, meal)
      setDesc(''); setCal('')
      await load()
    } catch (e: any) { onErr(String(e.message ?? e)) }
  }

  if (!data) return <p>Загрузка…</p>
  const goal = data.profile?.daily_calories ?? 0
  const eaten = Math.round(data.today_calories ?? 0)
  const pct = goal > 0 ? Math.min(100, Math.round((eaten / goal) * 100)) : 0

  return (
    <div>
      <h2 style={s.h}>🍽 Диета</h2>
      {data.profile
        ? <p style={s.sub}>{eaten}/{Math.round(goal)} ккал ({pct}%)</p>
        : <p style={s.sub}>Диета не настроена в боте — логирование всё равно работает.</p>}
      <div style={{ background: '#eee', borderRadius: 8, height: 10, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: '#31b545' }} />
      </div>
      <div style={s.card}>
        <div style={s.row}>
          {['Завтрак', 'Обед', 'Ужин', 'Еда'].map((m) => (
            <button key={m} onClick={() => setMeal(m)} style={meal === m ? s.btnActive : s.btnSm}>{m}</button>
          ))}
        </div>
        <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Что съел? (овсянка 100г)"
          style={{ ...s.input, marginTop: 8 }} maxLength={300} />
        <div style={{ ...s.row, marginTop: 8 }}>
          <input value={cal} onChange={(e) => setCal(e.target.value)} placeholder="Ккал" inputMode="decimal"
            style={s.inputSm} />
          <button onClick={log} style={s.primary}>+ Записать</button>
        </div>
      </div>
      {(data.today_log ?? []).map((e: any, i: number) => (
        <div key={i} style={s.card}>
          <div style={s.row}><span>{e.meal}: {e.description}</span><b>{Math.round(e.calories)}</b></div>
        </div>
      ))}
    </div>
  )
}
