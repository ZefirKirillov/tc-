import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { Ico, type IconName } from './icons'
import { hapticSelect, useBackButton } from './tg'
import { LoadError, Skeleton, useOnline } from './ui'
import Dashboard from './Dashboard'
import Tasks from './Tasks'
import Diet from './Diet'
import Stats from './Stats'
import Workout from './Workout'
import AI from './AI'

export type Tab = 'main' | 'workout' | 'tasks' | 'diet' | 'ai' | 'stats'

const TABS: Array<[Tab, IconName, string, string]> = [
  // key, icon, nav label, screen title
  ['main', 'orbit', 'Обзор', 'Обзор'],
  ['workout', 'dumbbell', 'Тренинг', 'Тренировка'],
  ['tasks', 'tasks', 'Задачи', 'Задачи'],
  ['diet', 'food', 'Диета', 'Питание'],
  ['ai', 'ai', 'CheckAI', 'CheckAI'],
  ['stats', 'chart', 'Прогресс', 'Прогресс'],
]

export default function App() {
  const [me, setMe] = useState<any>(null)
  const [loadErr, setLoadErr] = useState<unknown>(null)
  const [tab, setTab] = useState<Tab>('main')
  const online = useOnline()

  const loadMe = useCallback(() => {
    setLoadErr(null)
    api.me().then(setMe).catch((e) => setLoadErr(e))
  }, [])
  useEffect(loadMe, [loadMe])

  const switchTab = useCallback((k: Tab) => {
    setTab((cur) => {
      if (cur === k) return cur
      hapticSelect()
      window.scrollTo(0, 0)
      return k
    })
    // Counters on the overview (workouts, calories) change on other tabs — refresh silently.
    if (k === 'main') api.me().then(setMe).catch(() => {})
  }, [])

  // Telegram BackButton: from any tab back to the overview (screens can override with a higher priority).
  useBackButton(tab !== 'main' ? () => switchTab('main') : null, 0)

  const active = TABS.find(([k]) => k === tab)!

  let body: React.ReactNode
  if (!me && loadErr) {
    body = <LoadError error={loadErr} onRetry={loadMe} />
  } else if (!me) {
    body = (
      <div aria-busy="true">
        <Skeleton h={182} />
        <Skeleton h={54} />
        <Skeleton h={300} />
      </div>
    )
  } else {
    body = (
      <div className="screen" key={tab}>
        {tab === 'main' && <Dashboard me={me} setMe={setMe} go={switchTab} />}
        {tab === 'workout' && <Workout />}
        {tab === 'tasks' && <Tasks />}
        {tab === 'diet' && <Diet />}
        {tab === 'ai' && <AI />}
        {tab === 'stats' && <Stats />}
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1 className="topbar-title" style={{ margin: 0 }}>{active[3]}</h1>
        {me?.name && <span className="topbar-who label clip">{me.name}</span>}
      </header>
      {!online && (
        <div className="banner banner--offline" role="status">
          <Ico.offline size={16} /> Нет сети — изменения не сохранятся, пока связь не вернётся.
        </div>
      )}
      {body}
      {me && (
        <nav className="nav" aria-label="Разделы">
          <div className="nav-inner">
            {TABS.map(([k, icon, label]) => {
              const Icon = Ico[icon]
              return (
                <button key={k} onClick={() => switchTab(k)} className={`nav-item${k === tab ? ' is-active' : ''}`}
                  aria-current={k === tab ? 'page' : undefined}>
                  <Icon size={22} />
                  <span>{label}</span>
                </button>
              )
            })}
          </div>
        </nav>
      )}
    </div>
  )
}
