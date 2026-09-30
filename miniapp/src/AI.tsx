import { useEffect, useState } from 'react'
import { api } from './api'
import { s } from './styles'

export default function AI({ onErr }: { onErr: (e: string) => void }) {
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.aiLast().then((r) => { if (r.answer) setAnswer(r.answer) }).catch(() => {})
  }, [])

  async function ask(custom?: string) {
    const question = (custom ?? q).trim()
    if (question.length < 3 || busy) return
    setBusy(true)
    try {
      const r = custom === '__advice__' ? await api.aiAdvice() : await api.aiAsk(question)
      setAnswer(r.answer)
      if (!custom) setQ('')
    } catch (e: any) { onErr(String(e.message ?? e)) } finally { setBusy(false) }
  }

  return (
    <div>
      <h2 style={s.h}>🤖 CheckAI</h2>
      <button onClick={() => ask('__advice__')} disabled={busy} style={s.primary}>
        {busy ? 'Думаю…' : '💡 Дай совет'}
      </button>
      <div style={s.card}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Спроси что-нибудь…"
          style={s.input} maxLength={2000} onKeyDown={(e) => { if (e.key === 'Enter') ask() }} />
        <div style={{ marginTop: 8 }}>
          <button onClick={() => ask()} disabled={busy || q.trim().length < 3} style={s.primary}>
            {busy ? 'Думаю…' : 'Спросить'}
          </button>
        </div>
      </div>
      {answer && <div style={s.card}><div style={{ whiteSpace: 'pre-wrap', fontSize: 14 }}>{answer}</div></div>}
    </div>
  )
}
