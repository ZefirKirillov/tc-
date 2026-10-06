import { useEffect, useRef, useState } from 'react'
import { api, keep, peek } from './api'
import { Ico } from './icons'
import MainAction from './MainAction'
import { haptic } from './tg'
import { Empty, Section, Skeletons, Spinner, useBanner } from './ui'

export default function AI({ initialQuestion, onConsumed }: { initialQuestion?: string; onConsumed?: () => void } = {}) {
  const b = useBanner()
  const [q, setQ] = useState('')
  const [answer, setAnswerRaw] = useState<string | null>(() => peek('ai') ?? null)
  const [answerKind, setAnswerKind] = useState<'last' | 'advice' | 'ask'>('last')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(() => peek('ai') === undefined)

  const setAnswer = (a: string | null) => setAnswerRaw(keep('ai', a))
  // Once a new question is asked, the slower «last answer» load must not overwrite it.
  const askedRef = useRef(false)

  // A question typed on «Обзор» arrives here and is asked right away.
  useEffect(() => {
    if (!initialQuestion) return
    onConsumed?.()
    ask(false, initialQuestion)
  }, [])

  useEffect(() => {
    api.aiLast().then((r) => { if (r.answer && !askedRef.current) setAnswer(r.answer) }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  async function ask(advice = false, text?: string) {
    const question = (text ?? q).trim()
    if ((!advice && question.length < 3) || busy) return
    askedRef.current = true
    setBusy(true)
    b.clear()
    haptic('medium')
    try {
      const r = advice ? await api.aiAdvice() : await api.aiAsk(question)
      setAnswer(r.answer)
      setAnswerKind(advice ? 'advice' : 'ask')
      if (!advice) setQ('')
      haptic()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  const label = answerKind === 'advice' ? 'Совет' : answerKind === 'ask' ? 'Ответ' : 'Последний ответ'

  return (
    <div>
      {b.BannerEl}

      <button onClick={() => ask(true)} disabled={busy} className="cta" style={{ marginTop: 0 }}>
        {busy ? <Spinner className="cta-icon" fallback={<Ico.ai size={22} className="cta-icon" />} /> : <Ico.ai size={22} className="cta-icon" />}
        <span className="grow">
          <span style={{ fontWeight: 600, display: 'block' }}>{busy ? 'CheckAI думает…' : 'Совет на сегодня'}</span>
          <span className="row-meta">По твоим оценкам, тренировкам и питанию</span>
        </span>
        <Ico.arrow size={18} className="accent" />
      </button>

      <Section label="Вопрос">
        <textarea value={q} onChange={(e) => setQ(e.target.value)} placeholder="Например: как восстановиться после тяжёлой тренировки ног?"
          className="field" style={{ minHeight: 88 }} maxLength={2000} disabled={busy} />
        {q.length > 1500 && <div className="row-meta num" style={{ textAlign: 'right' }}>{q.length}/2000</div>}
        <MainAction float cfg={q.trim() ? { text: 'Спросить CheckAI', onClick: () => ask(), busy, disabled: q.trim().length < 3 } : null} />
      </Section>

      <Section label={label}>
        {(loading || busy) && <Skeletons n={1} h={120} />}
        {!loading && !busy && (answer
          ? <div className="panel answer">{answer}</div>
          : <Empty icon="ai" title="Здесь появится ответ" text="Задай вопрос или попроси совет — CheckAI учитывает твои данные из TrackCheck." />)}
      </Section>
    </div>
  )
}
