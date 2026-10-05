import { useCallback, useEffect, useState } from 'react'
import { api, keep } from './api'
import { Ico, type IconName } from './icons'
import { hapticSelect, startParam, useBackButton } from './tg'
import { LoadError, Skeleton, useOnline } from './ui'
import Dashboard from './Dashboard'
import Tasks from './Tasks'
import Diet from './Diet'
import Stats from './Stats'
import Workout from './Workout'
import AI from './AI'

export type Tab = 'main' | 'workout' | 'tasks' | 'diet' | 'ai' | 'stats'

// Five tabs in the island (Apple HIG: 3–5). CheckAI is opened from "Обзор".
const TABS: Array<[Tab, IconName, string]> = [
  ['main', 'orbit', 'Обзор'],
  ['workout', 'dumbbell', 'Тренинг'],
  ['diet', 'food', 'Питание'],
  ['tasks', 'tasks', 'Задачи'],
  ['stats', 'chart', 'Прогресс'],
]
const TITLES: Record<Tab, string> = {
  main: 'Обзор', workout: 'Тренировка', diet: 'Питание', tasks: 'Задачи', stats: 'Прогресс', ai: 'CheckAI',
}

// Deep link from bot notifications: ?tab=workout | diet | tasks | stats | ai | checkin
const DEEP = startParam()
const INITIAL_TAB: Tab = DEEP && DEEP in TITLES ? (DEEP as Tab) : 'main'

/** Title of the main screen: greeting by time of day + the user's name. */
function greeting(name?: string): string {
  const h = new Date().getHours()
  const hello = h >= 5 && h < 12 ? 'Доброе утро'
    : h >= 12 && h < 18 ? 'Добрый день'
    : h >= 18 && h < 23 ? 'Добрый вечер'
    : 'Доброй ночи'
  const n = (name ?? '').trim()
  return n && n !== 'друг' ? `${hello}, ${n}` : hello
}

/** Hide the island while typing — on phones it would ride up on the keyboard. */
function useTyping(): boolean {
  const [typing, setTyping] = useState(false)
  useEffect(() => {
    const isField = (t: EventTarget | null) =>
      t instanceof HTMLTextAreaElement ||
      (t instanceof HTMLInputElement && !['checkbox', 'radio', 'button', 'file', 'date'].includes(t.type))
    const on = (e: FocusEvent) => { if (isField(e.target)) setTyping(true) }
    const off = (e: FocusEvent) => { if (isField(e.target)) setTyping(false) }
    document.addEventListener('focusin', on)
    document.addEventListener('focusout', off)
    return () => { document.removeEventListener('focusin', on); document.removeEventListener('focusout', off) }
  }, [])
  return typing
}

export default function App() {
  const [me, setMe] = useState<any>(null)
  const [loadErr, setLoadErr] = useState<unknown>(null)
  const [tab, setTab] = useState<Tab>(INITIAL_TAB)
  // ?tab=checkin opens the check-in sheet once — not again on every return to "Обзор".
  const [deepCheckin, setDeepCheckin] = useState(DEEP === 'checkin')
  const online = useOnline()
  const typing = useTyping()

  const loadMe = useCallback(() => {
    setLoadErr(null)
    api.me().then((m) => {
      setMe(m)
      // Workout is the most used screen — warm its cache right after the shell is up.
      if (INITIAL_TAB !== 'workout') api.workout().then((d) => keep('workout', d)).catch(() => {})
    }).catch((e) => setLoadErr(e))
  }, [])
  useEffect(loadMe, [loadMe])

  const switchTab = useCallback((k: Tab) => {
    setDeepCheckin(false)
    setTab((cur) => {
      if (cur === k) return cur
      hapticSelect()
      window.scrollTo(0, 0)
      return k
    })
    // Counters on "Обзор" (workouts, calories) change on other tabs — refresh silently.
    if (k === 'main') api.me().then(setMe).catch(() => {})
  }, [])

  // Telegram BackButton: from any tab back to "Обзор" (sheets/sub-views override with higher priority).
  useBackButton(tab !== 'main' ? () => switchTab('main') : null, 0)

  const navTab: Tab = tab === 'ai' ? 'main' : tab

  let body: React.ReactNode
  if (!me && loadErr) {
    body = <LoadError error={loadErr} onRetry={loadMe} />
  } else if (!me) {
    body = (
      <div aria-busy="true">
        <Skeleton h={168} />
        <div className="mt" />
        <Skeleton h={300} />
      </div>
    )
  } else {
    body = (
      <div className="screen" key={tab}>
        {tab === 'main' && <Dashboard me={me} setMe={setMe} go={switchTab} openCheckin={deepCheckin} />}
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
        <h1 className="topbar-title wrap" style={{ margin: 0 }}>
          {tab === 'main' && me ? greeting(me.name) : TITLES[tab]}
        </h1>
      </header>
      {!online && (
        <div className="banner banner--offline" role="status">
          <Ico.offline size={16} /> Нет сети — изменения не сохранятся, пока связь не вернётся.
        </div>
      )}
      {body}
      {me && (
        <nav className={`nav${typing ? ' is-hidden' : ''}`} aria-label="Разделы" data-tour="nav">
          {TABS.map(([k, icon, label]) => {
            const Icon = Ico[icon]
            return (
              <button key={k} onClick={() => switchTab(k)} className={`nav-item${k === navTab ? ' is-active' : ''}`}
                aria-current={k === navTab ? 'page' : undefined}>
                <Icon size={22} />
                <span>{label}</span>
              </button>
            )
          })}
        </nav>
      )}
    </div>
  )
}
