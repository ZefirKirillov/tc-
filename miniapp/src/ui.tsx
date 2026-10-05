import { useEffect, useRef, useState } from 'react'
import { ApiError, errText, isNetworkError } from './api'
import { Ico, type IconName } from './icons'
import { hapticSelect, notifyErr } from './tg'

// Shared building blocks: feedback states, skeletons, confirm sheet, formatting.

// ---------- formatting ----------

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const nfPlain = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1, useGrouping: false })

/** Group thousands with a thin space, cap absurd values instead of overflowing. */
export function fmt(n: unknown, fallback = '—'): string {
  const v = typeof n === 'number' ? n : parseFloat(String(n ?? ''))
  if (!Number.isFinite(v)) return fallback
  // Russian convention: no separator in 4-digit numbers; thin space beyond (NBSP is too wide in mono)
  if (Math.abs(v) >= 1e7) return nf.format(Math.round(v / 1e6)).replace(/\s/g, '\u2009') + ' млн'
  if (Math.abs(v) < 1e4) return nfPlain.format(v)
  return nf.format(v).replace(/\s/g, '\u2009')
}

/** Plan weights arrive as numbers or strings like "80кг" / "собств. вес". */
export function fmtWeight(w: unknown): string {
  if (w == null || w === '' || w === 0) return ''
  const n = typeof w === 'number' ? w : Number(String(w).replace(',', '.'))
  return Number.isFinite(n) ? `${fmt(n)} кг` : String(w)
}

/** "2026-10-05" → "05.10"; anything unparsable is returned as is. */
export function fmtDate(d: string, withWeekday = false): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d ?? '')
  if (!m) return d
  const dd = `${m[3]}.${m[2]}`
  if (!withWeekday) return dd
  const wd = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'][new Date(+m[1], +m[2] - 1, +m[3]).getDay()]
  return `${dd} ${wd}`
}

// ---------- banners ----------

type Kind = 'err' | 'ok' | 'event'
const BANNER_ICON: Record<Kind, IconName> = { err: 'alert', ok: 'check', event: 'spark' }

export function Banner({ kind, text, onClose }: { kind: Kind; text: string; onClose: () => void }) {
  if (!text) return null
  const Icon = Ico[BANNER_ICON[kind]]
  return (
    <div className={`banner banner--${kind}`} role={kind === 'err' ? 'alert' : 'status'} onClick={onClose}>
      <Icon size={18} />
      <span className="wrap">{text}</span>
    </div>
  )
}

export function useBanner() {
  const [err, setErrText] = useState('')
  const [ok, setOkText] = useState('')
  const [okKind, setOkKind] = useState<'ok' | 'event'>('ok')
  const timer = useRef<number>()
  useEffect(() => () => window.clearTimeout(timer.current), [])

  function setErr(e: unknown) {
    const t = typeof e === 'string' ? e : errText(e)
    if (t) { setErrText(t); setOkText(''); notifyErr() }
  }
  function setOk(t: string, kind: 'ok' | 'event' = 'ok') {
    setOkText(t)
    setOkKind(kind)
    setErrText('')
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOkText(''), kind === 'event' ? 6000 : 3500)
  }
  function clear() { setErrText(''); setOkText('') }
  return {
    err, ok, setErr, setOk, clear,
    BannerEl: (
      <>
        <Banner kind="err" text={err} onClose={() => setErrText('')} />
        <Banner kind={okKind} text={ok} onClose={() => setOkText('')} />
      </>
    ),
  }
}

// ---------- loading / empty / error ----------

export function Skeleton({ h = 74 }: { h?: number }) {
  return <div className="skel" style={{ height: h }} aria-hidden="true" />
}

export function Skeletons({ n = 3, h = 74 }: { n?: number; h?: number }) {
  return (
    <div aria-busy="true" aria-label="Загрузка">
      {Array.from({ length: n }).map((_, i) => <Skeleton key={i} h={h} />)}
    </div>
  )
}

export function Empty({ icon, title, text, action }: {
  icon: IconName; title: string; text?: string; action?: React.ReactNode
}) {
  const Icon = Ico[icon]
  return (
    <div className="empty">
      <Icon size={28} className="empty-icon" />
      <div className="empty-title">{title}</div>
      {text && <div className="empty-text">{text}</div>}
      {action}
    </div>
  )
}

/** Full-block error for a failed initial load — always offers a retry. */
export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const net = isNetworkError(error)
  const auth = error instanceof ApiError && error.code === 'unauthorized'
  return (
    <Empty
      icon={net ? 'offline' : 'alert'}
      title={net ? 'Нет соединения' : auth ? 'Нужен вход через Telegram' : 'Не удалось загрузить'}
      text={errText(error)}
      action={!auth && (
        <button className="btn btn-ghost btn-sm" onClick={() => { hapticSelect(); onRetry() }}>
          <Ico.refresh size={16} /> Повторить
        </button>
      )}
    />
  )
}

export function useOnline(): boolean {
  const [on, setOn] = useState(navigator.onLine)
  useEffect(() => {
    const up = () => setOn(true)
    const down = () => setOn(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', down) }
  }, [])
  return on
}

// ---------- layout bits ----------

export function Section({ label, aux, children }: { label: string; aux?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="section">
      <div className="section-head">
        <span className="label">{label}</span>
        {aux}
      </div>
      {children}
    </section>
  )
}

export function Meter({ value, max, tone }: { value: number; max: number; tone?: 'warm' | 'over' }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0
  return (
    <div className={`meter${tone ? ` is-${tone}` : ''}`} role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <div className="meter-fill" style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Seg<T extends string | number>({ value, options, onChange, label }: {
  value: T; options: Array<[T, string]>; onChange: (v: T) => void; label?: string
}) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={String(v)} role="radio" aria-checked={v === value}
          className={`seg-opt${v === value ? ' is-on' : ''}`}
          onClick={() => { if (v !== value) { hapticSelect(); onChange(v) } }}>
          {text}
        </button>
      ))}
    </div>
  )
}

// ---------- confirm sheet ----------

export function Confirm({ title, body, okLabel = 'Подтвердить', danger, onOk, onCancel }: {
  title: string; body?: string; okLabel?: string; danger?: boolean; onOk: () => void; onCancel: () => void
}) {
  return (
    <div className="sheet-back" onClick={onCancel}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        {body && <p>{body}</p>}
        <div className="btn-bar">
          <button onClick={onCancel} className="btn btn-ghost btn-block">Отмена</button>
          <button onClick={onOk} className={`btn btn-block ${danger ? 'btn-danger' : 'btn-primary'}`}
            style={danger ? { borderColor: 'var(--danger)' } : undefined}>{okLabel}</button>
        </div>
      </div>
    </div>
  )
}
