import { useEffect, useLayoutEffect, useState } from 'react'
import { hapticSelect, notifyOk, useBackButton } from './tg'

// First-run tutorial: a few spotlight steps over the real UI (elements marked with data-tour="…").

type Step = { target?: string; title: string; text: string }

const STEPS: Step[] = [
  { title: 'Привет! Это TrackCheck', text: 'Твой день — на одном экране. Покажу главное, это займёт 20 секунд.' },
  { target: 'hero', title: 'Твоя орбита', text: 'Кольца показывают чек-ин, тренировки за месяц и калории. В центре — сколько дней подряд ты в деле 🔥' },
  { target: 'ask', title: 'Спроси CheckAI', text: 'Напиши вопрос прямо здесь — CheckAI ответит с учётом твоих тренировок, питания и оценок.' },
  { target: 'checkin', title: 'Чек-ин — минута в день', text: 'Нажми на кружок и оцени сон, зависание и настрой от 1 до 10. 7 и выше — золото. Еду и активность TrackCheck оценит сам.' },
  { target: 'today', title: 'Виджеты дня', text: 'Тренировка, питание и задачи. Чем ближе к цели — тем ярче золотая рамка. Нажми на виджет, чтобы открыть раздел.' },
  { target: 'nav', title: 'Разделы внизу', text: 'Тренинг, питание, задачи и прогресс. В зале открывай «Тренинг» и отмечай упражнения по ходу.' },
  { title: 'Готово!', text: 'Напоминания будут приходить в чат с ботом. Хорошего дня 💪' },
]

type Rect = { top: number; left: number; width: number; height: number }

function measure(target?: string): Rect | null {
  if (!target) return null
  const el = document.querySelector(`[data-tour="${target}"]`)
  if (!el) return null
  const r = el.getBoundingClientRect()
  const pad = 6
  return { top: r.top - pad, left: r.left - pad, width: r.width + pad * 2, height: r.height + pad * 2 }
}

export default function Tour({ onDone }: { onDone: () => void }) {
  const [i, setI] = useState(0)
  const [rect, setRect] = useState<Rect | null>(null)
  const step = STEPS[i]
  const last = i === STEPS.length - 1

  // Bring the target into view, then measure it (again on resize/scroll).
  useLayoutEffect(() => {
    const el = step.target ? document.querySelector(`[data-tour="${step.target}"]`) : null
    if (el && step.target !== 'nav') el.scrollIntoView({ block: 'center', behavior: 'instant' as ScrollBehavior })
    setRect(measure(step.target))
    const update = () => setRect(measure(step.target))
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => { window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true) }
  }, [i])

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  useBackButton(() => (i > 0 ? setI(i - 1) : onDone()), 10)

  function next() {
    hapticSelect()
    if (last) { notifyOk(); onDone() } else setI(i + 1)
  }

  // Card goes below the spotlight when there is room, otherwise above; centered without a target.
  const vh = window.innerHeight
  let cardStyle: React.CSSProperties
  if (!rect) cardStyle = { top: '50%', transform: 'translateY(-50%)' }
  else if (rect.top + rect.height + 230 < vh) cardStyle = { top: rect.top + rect.height + 14 }
  else cardStyle = { bottom: vh - rect.top + 14 }

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Знакомство с TrackCheck">
      {rect
        ? <div className="tour-spot" style={{ ...rect, borderRadius: step.target === 'nav' ? 999 : undefined }} />
        : <div className="tour-shade" />}
      <div className="tour-card" style={cardStyle} key={i}>
        <h3>{step.title}</h3>
        <p>{step.text}</p>
        <div className="tour-foot">
          <div className="tour-dots" aria-hidden="true">
            {STEPS.map((_, k) => <i key={k} className={k === i ? 'is-on' : ''} />)}
          </div>
          {!last && <button className="btn btn-quiet btn-sm" onClick={onDone}>Пропустить</button>}
          <button className="btn btn-primary btn-sm" style={{ minWidth: 92 }} onClick={next}>
            {last ? 'Начать' : i === 0 ? 'Покажи' : 'Дальше'}
          </button>
        </div>
      </div>
    </div>
  )
}
