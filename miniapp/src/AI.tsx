import { useEffect, useState } from 'react'
import { api, haptic } from './api'
import { s } from './styles'
import { Skeletons, useBanner } from './ui'

export default function AI() {
  const b = useBanner()
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.aiLast().then((r) => { if (r.answer) setAnswer(r.answer) }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  async function ask(advice = false) {
    const question = q.trim()
    if ((!advice && question.length < 3) || busy) return
    setBusy(true)
    b.clear()
    haptic('medium')
    try {
      const r = advice ? await api.aiAdvice() : await api.aiAsk(question)
      setAnswer(r.answer)
      if (!advice) setQ('')
      haptic()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  return (
    <div>
      <h2 style={s.h}>🤖 Оракул nebulы</h2>
      {b.BannerEl}
      <button onClick={() => ask(true)} disabled={busy} style={s.primary}>
        {busy ? '🌌 Совещаюсь со звёздами…' : '💡 Дай совет'}
      </button>
      <div style={s.card}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Спроси у космоса…"
          style={s.input} maxLength={2000} onKeyDown={(e) => { if (e.key === 'Enter') ask() }} />
        <div style={{ marginTop: 8, marginBottom: 0 }}>
          <button onClick={() => ask()} disabled={busy || q.trim().length < 3} style={s.primary}>
            {busy ? '🌌…' : 'Спросить ✨'}
          </button>
        </div>
      </div>
      {loading && <Skeletons n={1} />}
      {answer && <div style={s.card}><div style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{answer}</div></div>}
    </div>
  )
}
