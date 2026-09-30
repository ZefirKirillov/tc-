import { useEffect, useState } from 'react'
import { api, errText, haptic } from './api'
import { s } from './styles'
import { Skeletons } from './ui'
import Dashboard from './Dashboard'
import Tasks from './Tasks'
import Diet from './Diet'
import Stats from './Stats'
import Workout from './Workout'
import AI from './AI'

type Tab = 'main' | 'workout' | 'tasks' | 'diet' | 'ai' | 'stats'

const TABS: Array<[Tab, string, string]> = [
  ['main', '🏠', 'Главная'],
  ['workout', '🏋️', 'Тренировки'],
  ['tasks', '📝', 'Задачи'],
  ['diet', '🍽', 'Диета'],
  ['ai', '🤖', 'CheckAI'],
  ['stats', '📊', 'Статистика'],
]

export default function App() {
  const [me, setMe] = useState<any>(null)
  const [err, setErr] = useState('')
  const [tab, setTab] = useState<Tab>('main')

  useEffect(() => {
    api.me().then(setMe).catch((e) => setErr(errText(e)))
  }, [])

  function switchTab(k: Tab) {
    setTab(k)
    haptic()
  }

  if (err && !me)
    return (
      <div style={s.page}>
        <style>{'@keyframes tc-shimmer { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }'}</style>
        <h2 style={s.h}>TrackCheck</h2>
        <p style={s.err}>⚠️ {err}</p>
        <p style={s.hint}>Открой через Telegram (кнопка Mini App).</p>
      </div>
    )
  if (!me)
    return (
      <div style={s.page}>
        <style>{'@keyframes tc-shimmer { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }'}</style>
        <h2 style={s.h}>TrackCheck</h2>
        <Skeletons />
      </div>
    )

  const active = TABS.find(([k]) => k === tab)

  return (
    <div style={s.page}>
      <style>{'@keyframes tc-shimmer { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }'}</style>
      {err && <p style={s.err} onClick={() => setErr('')}>{err}</p>}
      <div style={{ ...s.sub, marginBottom: 4 }}>{active?.[2]} · {me.name}</div>
      {tab === 'main' && <Dashboard me={me} setMe={setMe} />}
      {tab === 'workout' && <Workout />}
      {tab === 'tasks' && <Tasks />}
      {tab === 'diet' && <Diet />}
      {tab === 'ai' && <AI />}
      {tab === 'stats' && <Stats />}
      <nav style={s.nav}>
        {TABS.map(([k, icon]) => (
          <button key={k} onClick={() => switchTab(k)} style={k === tab ? s.navActive : s.navBtn} aria-label={k}>{icon}</button>
        ))}
      </nav>
    </div>
  )
}
