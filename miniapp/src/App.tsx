import { useEffect, useState } from 'react'
import { api } from './api'
import { s } from './styles'
import Dashboard from './Dashboard'
import Tasks from './Tasks'
import Diet from './Diet'
import Stats from './Stats'
import Workout from './Workout'
import AI from './AI'

type Tab = 'main' | 'workout' | 'tasks' | 'diet' | 'ai' | 'stats'

const TABS: Array<[Tab, string]> = [
  ['main', '🏠'],
  ['workout', '🏋️'],
  ['tasks', '📝'],
  ['diet', '🍽'],
  ['ai', '🤖'],
  ['stats', '📊'],
]

export default function App() {
  const [me, setMe] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('main')

  useEffect(() => {
    api.me().then(setMe).catch((e) => setErr(String(e.message ?? e)))
  }, [])

  if (err && !me)
    return <div style={s.page}><p>⚠️ {err}</p><p style={s.hint}>Открой через Telegram (кнопка Mini App).</p></div>
  if (!me) return <div style={s.page}><p>Загрузка…</p></div>

  return (
    <div style={s.page}>
      {err && <p style={s.err}>{err}</p>}
      {tab === 'main' && <Dashboard me={me} setMe={setMe} onErr={setErr} />}
      {tab === 'workout' && <Workout onErr={setErr} />}
      {tab === 'tasks' && <Tasks onErr={setErr} />}
      {tab === 'diet' && <Diet onErr={setErr} />}
      {tab === 'ai' && <AI onErr={setErr} />}
      {tab === 'stats' && <Stats onErr={setErr} />}
      <nav style={s.nav}>
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={k === tab ? s.navActive : s.navBtn}>{label}</button>
        ))}
      </nav>
    </div>
  )
}
