import { useEffect, useRef, useSyncExternalStore } from 'react'

// Thin wrapper over window.Telegram.WebApp. Every call is guarded so the app
// still runs in a plain browser (dev mode) where platform === 'unknown'.

export const tg = (window as any).Telegram?.WebApp
export const inTelegram: boolean = !!tg && !!tg.platform && tg.platform !== 'unknown'

function atLeast(v: string): boolean {
  try { return !!tg?.isVersionAtLeast?.(v) } catch { return false }
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

// ---------- theme ----------

type Scheme = 'dark' | 'light'
const themeListeners = new Set<() => void>()
let scheme: Scheme = 'dark'

function detectScheme(): Scheme {
  if (inTelegram && tg.colorScheme) return tg.colorScheme === 'light' ? 'light' : 'dark'
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function applyTheme() {
  scheme = detectScheme()
  document.documentElement.dataset.theme = scheme
  const bg = cssVar('--bg')
  const bar = cssVar('--bg-raise')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bg)
  try { if (atLeast('6.1')) { tg.setHeaderColor(bg); tg.setBackgroundColor(bg) } } catch { /* noop */ }
  try { if (atLeast('7.10')) tg.setBottomBarColor(bar) } catch { /* noop */ }
  themeListeners.forEach((l) => l())
}

export function useScheme(): Scheme {
  return useSyncExternalStore(
    (cb) => { themeListeners.add(cb); return () => themeListeners.delete(cb) },
    () => scheme,
  )
}

export function initTelegram() {
  applyTheme()
  if (inTelegram) tg.onEvent?.('themeChanged', applyTheme)
  else window.matchMedia?.('(prefers-color-scheme: light)').addEventListener?.('change', applyTheme)
  try {
    tg?.ready()
    tg?.expand()
  } catch { /* not in Telegram — dev mode */ }
  // Long lists scroll vertically; don't let a scroll gesture minimise the app.
  try { if (atLeast('7.7')) tg.disableVerticalSwipes() } catch { /* noop */ }
}

// ---------- haptics ----------

export function haptic(kind: 'light' | 'medium' | 'heavy' = 'light') {
  try { tg?.HapticFeedback?.impactOccurred(kind) } catch { /* noop */ }
}
export function hapticSelect() {
  try { tg?.HapticFeedback?.selectionChanged() } catch { /* noop */ }
}
export function notifyOk() {
  try { tg?.HapticFeedback?.notificationOccurred('success') } catch { /* noop */ }
}
export function notifyErr() {
  try { tg?.HapticFeedback?.notificationOccurred('error') } catch { /* noop */ }
}

// ---------- MainButton ----------

export type MainCfg = { text: string; onClick: () => void; disabled?: boolean; busy?: boolean } | null

/** Drives Telegram's MainButton while mounted. Returns true when the native
 *  button is in use — otherwise the caller renders an in-page fallback.
 *  Only one component per screen should use it at a time. */
export function useMainButton(cfg: MainCfg): boolean {
  const ref = useRef(cfg)
  ref.current = cfg
  const mb = inTelegram ? tg.MainButton : null
  const theme = useScheme()

  useEffect(() => {
    if (!mb) return
    const h = () => {
      const c = ref.current
      if (c && !c.disabled && !c.busy) { haptic('medium'); c.onClick() }
    }
    mb.onClick(h)
    return () => {
      mb.offClick(h)
      try { mb.hideProgress(); mb.hide() } catch { /* noop */ }
    }
  }, [mb])

  const visible = !!cfg
  const text = cfg?.text
  const disabled = !!cfg?.disabled
  const busy = !!cfg?.busy
  useEffect(() => {
    if (!mb) return
    try {
      if (!visible) { mb.hideProgress(); mb.hide(); return }
      mb.setParams({
        text,
        color: disabled ? cssVar('--surface-2') : cssVar('--accent'),
        text_color: disabled ? cssVar('--text-3') : cssVar('--accent-ink'),
        is_active: !disabled,
        is_visible: true,
      })
      if (busy) mb.showProgress(false)
      else mb.hideProgress()
    } catch { /* noop */ }
  }, [mb, visible, text, disabled, busy, theme])

  return !!mb
}

// ---------- BackButton ----------
// Several components may want the back button at once (app: "to home",
// a screen: "close sub-view"). Highest priority wins; ties → latest.

type BackEntry = { h: () => void; p: number; id: number }
const backStack: BackEntry[] = []
let backSeq = 0
let backBound: (() => void) | null = null

function syncBack() {
  const bb = inTelegram && atLeast('6.1') ? tg.BackButton : null
  if (!bb) return
  const top = [...backStack].sort((a, b) => a.p - b.p || a.id - b.id).pop()
  if (backBound) bb.offClick(backBound)
  backBound = top?.h ?? null
  if (backBound) { bb.onClick(backBound); bb.show() } else bb.hide()
}

export function useBackButton(handler: (() => void) | null, priority = 1) {
  const ref = useRef(handler)
  ref.current = handler
  const active = !!handler
  useEffect(() => {
    if (!active) return
    const entry: BackEntry = { h: () => { hapticSelect(); ref.current?.() }, p: priority, id: ++backSeq }
    backStack.push(entry)
    syncBack()
    return () => {
      backStack.splice(backStack.indexOf(entry), 1)
      syncBack()
    }
  }, [active, priority])
  return inTelegram
}

// ---------- persistent flags (tutorial seen, …) ----------
// Telegram CloudStorage follows the user across devices; localStorage is the fallback.

function localGet(key: string): string | null {
  try { return window.localStorage.getItem(key) } catch { return null }
}
function localSet(key: string, value: string) {
  try { window.localStorage.setItem(key, value) } catch { /* private mode */ }
}

export function cloudGet(key: string): Promise<string | null> {
  const local = localGet(key)
  const cs = inTelegram && atLeast('6.9') ? tg.CloudStorage : null
  if (!cs || local) return Promise.resolve(local)
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(local), 1500)
    try {
      cs.getItem(key, (err: unknown, value?: string) => {
        window.clearTimeout(timer)
        resolve(err ? local : (value || local || null))
      })
    } catch { window.clearTimeout(timer); resolve(local) }
  })
}

export function cloudSet(key: string, value: string) {
  localSet(key, value)
  try { if (inTelegram && atLeast('6.9')) tg.CloudStorage.setItem(key, value) } catch { /* noop */ }
}

// ---------- deep link ----------
/** ?tab=workout|diet|tasks|stats|ai|checkin — used by bot notifications. */
export function startParam(): string | null {
  try { return new URLSearchParams(window.location.search).get('tab') } catch { return null }
}
