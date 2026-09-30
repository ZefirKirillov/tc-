import { useState } from 'react'
import { s } from './styles'

// Reusable bits: loading skeletons, inline confirm dialog, error/toast banner.

export function Skeletons({ n = 3 }: { n?: number }) {
  return (
    <>
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} style={s.skeleton} />
      ))}
    </>
  )
}

export function Banner({ kind, text, onClose }: { kind: 'err' | 'ok'; text: string; onClose: () => void }) {
  if (!text) return null
  return (
    <p style={kind === 'err' ? s.err : s.toast} onClick={onClose}>
      {text}
    </p>
  )
}

export function Confirm({ title, body, okLabel = 'Подтвердить', onOk, onCancel }: {
  title: string; body?: string; okLabel?: string; onOk: () => void; onCancel: () => void;
}) {
  return (
    <div style={s.confirmOverlay} onClick={onCancel}>
      <div style={s.confirmBox} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ margin: '0 0 8px' }}>{title}</h3>
        {body && <p style={s.sub}>{body}</p>}
        <div style={{ ...s.row, marginTop: 16, marginBottom: 0 }}>
          <button onClick={onCancel} style={s.btnSm}>Отмена</button>
          <button onClick={onOk} style={s.primary}>{okLabel}</button>
        </div>
      </div>
    </div>
  )
}

export function useBanner() {
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  function showErr(e: unknown) {
    const t = e instanceof Error ? e.message : String(e)
    if (t) setErr(t)
  }
  function showOk(t: string) {
    setOk(t)
    setTimeout(() => setOk(''), 4000)
  }
  function clear() { setErr(''); setOk('') }
  return { err, ok, setErr: showErr, setOk: showOk, clear, BannerEl: (
    <>
      <Banner kind="err" text={err} onClose={() => setErr('')} />
      <Banner kind="ok" text={ok} onClose={() => setOk('')} />
    </>
  )}
}
