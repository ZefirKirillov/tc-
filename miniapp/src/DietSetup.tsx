import { useEffect, useState } from 'react'
import { api } from './api'
import { Ico } from './icons'
import MainAction from './MainAction'
import { hapticSelect, inTelegram, notifyOk, useBackButton, type MainCfg } from './tg'
import { fmt, useBanner } from './ui'

// First visit to "Питание": set the daily calorie goal. Same questions, ranges and
// formula as the bot's diet setup — the server does the math (POST /api/diet/profile).

type Goal = 'loss' | 'maintain' | 'gain'
type Form = { gender: 'male' | 'female' | null; age: string; height: string; weight: string; activity: number | null; goal: Goal | null; change: string; days: string }

const ACTIVITY: Array<[number, string, string]> = [
  [1.2, 'Сидячий', 'Почти без тренировок'],
  [1.375, 'Лёгкий', '1–3 тренировки в неделю'],
  [1.55, 'Умеренный', '3–5 тренировок в неделю'],
  [1.725, 'Высокий', '6–7 тренировок в неделю'],
  [1.9, 'Очень высокий', 'Физическая работа + спорт'],
]
const GOALS: Array<[Goal, string, string]> = [
  ['loss', 'Снизить вес', 'Небольшой дефицит калорий'],
  ['maintain', 'Держать вес', 'Норма по твоему расходу'],
  ['gain', 'Набрать вес', 'Небольшой профицит калорий'],
]

const n = (s: string) => parseFloat(s.replace(',', '.'))
const inRange = (s: string, lo: number, hi: number) => { const v = n(s); return Number.isFinite(v) && v >= lo && v <= hi }

export default function DietSetup({ onDone }: { onDone: () => void }) {
  const b = useBanner()
  const [step, setStep] = useState(0)
  const [f, setF] = useState<Form>({ gender: null, age: '', height: '', weight: '', activity: null, goal: null, change: '', days: '90' })
  const [result, setResult] = useState<{ daily_calories: number; warning: string | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (p: Partial<Form>) => setF({ ...f, ...p })

  const bodyOk = inRange(f.age, 10, 120) && Number.isInteger(n(f.age)) && inRange(f.height, 100, 250) && inRange(f.weight, 20, 300)
  const targetOk = f.goal === 'maintain' || (inRange(f.change, 0.1, 100) && inRange(f.days, 7, 730) && Number.isInteger(n(f.days)))

  function payload(preview: boolean) {
    return {
      gender: f.gender, age: parseInt(f.age), height: n(f.height), weight: n(f.weight), activity: f.activity, goal: f.goal,
      ...(f.goal !== 'maintain' ? { change: n(f.change), days: parseInt(f.days) } : {}), preview,
    }
  }

  async function calculate() {
    setBusy(true)
    try {
      setResult(await api.dietProfile(payload(true)))
      hapticSelect()
      setStep(4)
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function save() {
    setBusy(true)
    try {
      await api.dietProfile(payload(false))
      notifyOk()
      onDone()
    } catch (e) { b.setErr(e); setBusy(false) }
  }

  // Choice steps advance on tap; input steps use the main button.
  function choose(p: Partial<Form>, next: number) {
    hapticSelect()
    set(p)
    window.setTimeout(() => setStep(next), 120)
  }

  useEffect(() => { window.scrollTo(0, 0) }, [step])
  useBackButton(step > 0 ? () => setStep(step === 4 ? 3 : step - 1) : null, 1)

  let main: MainCfg = null
  if (step === 1) main = { text: 'Дальше', onClick: () => { hapticSelect(); setStep(2) }, disabled: !bodyOk }
  else if (step === 3 && f.goal) main = { text: 'Рассчитать норму', onClick: calculate, busy, disabled: !targetOk }
  else if (step === 4) main = { text: 'Сохранить и начать', onClick: save, busy }

  const steps = 4
  return (
    <div>
      {b.BannerEl}
      <div className="steps" aria-label={`Шаг ${Math.min(step + 1, steps)} из ${steps}`}>
        {Array.from({ length: steps }).map((_, i) => <i key={i} className={i <= Math.min(step, steps - 1) ? 'is-on' : ''} />)}
      </div>

      {step === 0 && (
        <>
          <h2 style={{ margin: '4px 0 6px' }}>Посчитаем твою норму</h2>
          <p className="muted" style={{ margin: '0 0 18px' }}>Четыре коротких вопроса — и дневник питания готов. Начнём с пола:</p>
          <div className="opts">
            {([['male', 'Мужской'], ['female', 'Женский']] as const).map(([g, label]) => (
              <button key={g} className={`opt${f.gender === g ? ' is-on' : ''}`} onClick={() => choose({ gender: g }, 1)}>{label}</button>
            ))}
          </div>
        </>
      )}

      {step === 1 && (
        <>
          <h2 style={{ margin: '4px 0 18px' }}>О тебе</h2>
          <div className="vstack" style={{ gap: 12 }}>
            {([['age', 'Возраст', 'лет', 'numeric'], ['height', 'Рост', 'см', 'decimal'], ['weight', 'Вес', 'кг', 'decimal']] as const).map(([k, label, unit, mode]) => (
              <label key={k} className="hstack" style={{ gap: 12 }}>
                <span className="grow" style={{ fontWeight: 600 }}>{label}</span>
                <input className="field field-num" style={{ width: 110, textAlign: 'right' }} inputMode={mode} maxLength={5}
                  value={f[k]} onChange={(e) => set({ [k]: e.target.value } as Partial<Form>)} placeholder={unit}
                  autoFocus={k === 'age'} />
                <span className="muted" style={{ width: 28 }}>{unit}</span>
              </label>
            ))}
          </div>
          {!bodyOk && (f.age || f.height || f.weight) && (
            <div className="row-meta mt">Возраст 10–120, рост 100–250 см, вес 20–300 кг.</div>
          )}
        </>
      )}

      {step === 2 && (
        <>
          <h2 style={{ margin: '4px 0 18px' }}>Сколько двигаешься?</h2>
          <div className="cells">
            {ACTIVITY.map(([v, title, sub]) => (
              <button key={v} className="cell" onClick={() => choose({ activity: v }, 3)}>
                <span className="grow">
                  <span className="cell-title" style={{ display: 'block' }}>{title}</span>
                  <span className="cell-sub" style={{ display: 'block' }}>{sub}</span>
                </span>
                {f.activity === v ? <Ico.check size={20} className="cell-done" /> : <Ico.arrow size={16} className="cell-chev" />}
              </button>
            ))}
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <h2 style={{ margin: '4px 0 18px' }}>Какая цель?</h2>
          <div className="cells">
            {GOALS.map(([g, title, sub]) => (
              <button key={g} className="cell" onClick={() => { hapticSelect(); set({ goal: g }) }}>
                <span className="grow">
                  <span className="cell-title" style={{ display: 'block' }}>{title}</span>
                  <span className="cell-sub" style={{ display: 'block' }}>{sub}</span>
                </span>
                {f.goal === g && <Ico.check size={20} className="cell-done" />}
              </button>
            ))}
          </div>
          {f.goal && f.goal !== 'maintain' && (
            <div className="panel mt vstack" style={{ gap: 12 }}>
              <label className="hstack" style={{ gap: 12 }}>
                <span className="grow" style={{ fontWeight: 600 }}>{f.goal === 'loss' ? 'Сбросить' : 'Набрать'}</span>
                <input className="field field-num" style={{ width: 110, textAlign: 'right' }} inputMode="decimal" maxLength={5}
                  value={f.change} onChange={(e) => set({ change: e.target.value })} placeholder="5" />
                <span className="muted" style={{ width: 28 }}>кг</span>
              </label>
              <label className="hstack" style={{ gap: 12 }}>
                <span className="grow" style={{ fontWeight: 600 }}>За</span>
                <input className="field field-num" style={{ width: 110, textAlign: 'right' }} inputMode="numeric" maxLength={3}
                  value={f.days} onChange={(e) => set({ days: e.target.value })} placeholder="90" />
                <span className="muted" style={{ width: 28 }}>дн.</span>
              </label>
              {!targetOk && f.change && <div className="row-meta">От 0,1 до 100 кг, за 7–730 дней.</div>}
            </div>
          )}
        </>
      )}

      {step === 4 && result && (
        <div style={{ textAlign: 'center', paddingTop: 12 }}>
          <div className="muted">Твоя норма</div>
          <div className="num" style={{ fontSize: 52, fontWeight: 650, lineHeight: 1.1, margin: '6px 0' }}>{fmt(result.daily_calories)}</div>
          <div className="muted">ккал в день</div>
          {result.warning && (
            <div className="banner banner--event mt" style={{ textAlign: 'left' }}>
              <Ico.alert size={18} /><span className="wrap">{result.warning.replace(/^⚠️\s*/, '')}</span>
            </div>
          )}
          <p className="muted" style={{ marginTop: 18, fontSize: 14 }}>
            Еда за день будет оцениваться по тому, насколько ты близок к этой цифре.
          </p>
          {!inTelegram && <button className="btn btn-quiet" onClick={() => setStep(3)}>Изменить ответы</button>}
        </div>
      )}

      {!inTelegram && step > 0 && step < 4 && (
        <button onClick={() => setStep(step - 1)} className="btn btn-quiet mt"><Ico.back size={16} /> Назад</button>
      )}
      <MainAction cfg={main} float />
    </div>
  )
}
