import { useEffect, useRef, useState } from 'react'
import { api, keep, peek } from './api'
import { Ico } from './icons'
import MainAction from './MainAction'
import { haptic, notifyOk, type MainCfg } from './tg'
import DietSetup from './DietSetup'
import { Empty, fmt, LoadError, Meter, Section, Seg, Sheet, Skeleton, Skeletons, useBanner } from './ui'

const MEALS: Array<[string, string]> = [['Завтрак', 'Завтрак'], ['Обед', 'Обед'], ['Ужин', 'Ужин'], ['Еда', 'Еда']]

function num(s: string): number {
  return parseFloat(s.replace(',', '.'))
}

export default function Diet() {
  const b = useBanner()
  const [data, setData] = useState<any>(() => peek('diet') ?? null)
  const [loadErr, setLoadErr] = useState<unknown>(null)
  const [desc, setDesc] = useState('')
  const [cal, setCal] = useState('')
  const [meal, setMeal] = useState('Еда')
  const [busy, setBusy] = useState(false)
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoPrev, setPhotoPrev] = useState<{ url: string; description: string; calories: number | null } | null>(null)
  const [manualCal, setManualCal] = useState('')
  const [body, setBody] = useState<any>(() => peek('body') ?? null)
  const [weight, setWeight] = useState('')
  const [fat, setFat] = useState('')
  const [bodyBusy, setBodyBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  // Entry forms live in sheets — the screen itself only shows the day.
  const [adding, setAdding] = useState(false)
  const [bodyOpen, setBodyOpen] = useState(false)

  async function load() {
    try {
      const [d, bd] = await Promise.all([api.diet(), api.body().catch(() => null)])
      setData(keep('diet', d))
      setBody(keep('body', bd))
      setLoadErr(null)
    } catch (e) { if (data) b.setErr(e); else setLoadErr(e) }
  }
  useEffect(() => { load() }, [])

  // Release the object URL of the previous photo preview.
  useEffect(() => () => { if (photoPrev) URL.revokeObjectURL(photoPrev.url) }, [photoPrev])

  async function log() {
    const calories = num(cal)
    if (!desc.trim() || !(calories > 0)) { b.setErr('Опиши блюдо и укажи калории.'); return }
    setBusy(true)
    try {
      await api.logFood(desc.trim(), calories, meal)
      setDesc(''); setCal('')
      setAdding(false)
      notifyOk()
      b.setOk('Записано.')
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function onPhoto(file: File | undefined) {
    if (!file) return
    if (file.size > 5 * 1024 * 1024) { b.setErr('Фото слишком большое (макс. 5 МБ).'); return }
    setPhotoBusy(true)
    b.clear()
    try {
      const r = await api.dietPhoto(file)
      setPhotoPrev({ url: URL.createObjectURL(file), description: r.description, calories: r.calories })
      haptic()
      if (r.needs_manual) b.setErr('Блюдо распознано, но калории оценить не удалось — введи вручную.')
    } catch (e) { b.setErr(e) } finally {
      setPhotoBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function confirmPhoto() {
    if (!photoPrev) return
    const calories = photoPrev.calories ?? num(manualCal)
    if (!(calories > 0)) { b.setErr('Укажи калории числом.'); return }
    setBusy(true)
    try {
      await api.logFood(photoPrev.description, calories, meal)
      setPhotoPrev(null); setManualCal('')
      setAdding(false)
      notifyOk()
      b.setOk('Записано.')
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function saveBody() {
    const w = weight.trim() ? num(weight) : null
    const f = fat.trim() ? num(fat) : null
    if (w === null && f === null) return
    setBodyBusy(true)
    try {
      await api.saveBody(w, f)
      setWeight(''); setFat('')
      setBodyOpen(false)
      notifyOk()
      b.setOk('Замер сохранён.')
      await load()
    } catch (e) { b.setErr(e) } finally { setBodyBusy(false) }
  }

  // One primary action at a time: photo confirm > manual entry.
  // One primary action at a time, depending on what is open.
  let main: MainCfg
  if (adding && photoPrev) main = { text: 'Подтвердить блюдо', onClick: confirmPhoto, busy, disabled: photoPrev.calories == null && !(num(manualCal) > 0) }
  else if (adding) main = { text: 'Записать', onClick: log, busy, disabled: !desc.trim() || !(num(cal) > 0) }
  else if (bodyOpen) main = { text: 'Сохранить замер', onClick: saveBody, busy: bodyBusy, disabled: !weight.trim() && !fat.trim() }
  else main = { text: 'Добавить еду', onClick: () => setAdding(true) }

  function closeAdd() {
    setAdding(false)
    setPhotoPrev(null)
    setManualCal('')
  }

  if (!data) {
    if (loadErr) return <LoadError error={loadErr} onRetry={() => { setLoadErr(null); load() }} />
    return <div><Skeleton h={88} /><div className="mt" /><Skeletons n={2} h={56} /></div>
  }

  // The calorie tracker needs a daily goal — first visit to the tab sets it up right here.
  if (!data.profile) return <DietSetup onDone={load} />

  const goal = data.profile.daily_calories ?? 0
  const eaten = Math.round(data.today_calories ?? 0)
  const left = Math.round(goal - eaten)
  const entries: any[] = data.today_log ?? []

  const sheetOpen = adding || bodyOpen

  return (
    <div>
      {!sheetOpen && b.BannerEl}

      <div className="panel">
        <div className="hstack spread" style={{ alignItems: 'baseline' }}>
          <span className="label">Сегодня</span>
          <span className="label" style={left < 0 ? { color: 'var(--danger)' } : undefined}>
            {left >= 0 ? `осталось ${fmt(left)}` : `сверх нормы ${fmt(-left)}`}
          </span>
        </div>
        <div className="num clip" style={{ fontSize: 30, fontWeight: 600, margin: '4px 0 10px' }}>
          {fmt(eaten)}<span className="muted" style={{ fontSize: 15 }}> / {fmt(Math.round(goal))} ккал</span>
        </div>
        <Meter value={eaten} max={goal} tone={eaten > goal ? 'over' : undefined} />
      </div>

      {!sheetOpen && <MainAction cfg={main} float />}

      <Section label="Журнал дня" aux={entries.length > 0 && <span className="num muted" style={{ fontSize: 12 }}>{entries.length}</span>}>
        {entries.length === 0
          ? <Empty icon="food" title="Пока ничего не записано" text="Нажми «Добавить еду» — текстом или по фото." />
          : (
            <div className="rows">
              {entries.map((e, i) => (
                <div key={i} className="row">
                  <div className="grow wrap">
                    <div className="label">{e.meal}</div>
                    <div>{e.description}</div>
                  </div>
                  <span className="num" style={{ flex: 'none' }}>{fmt(Math.round(e.calories))}</span>
                </div>
              ))}
            </div>
          )}
      </Section>

      <Section label="Тело">
        <div className="cells">
          <button className="cell" onClick={() => setBodyOpen(true)}>
            <span className="cell-icon is-metal"><Ico.scale size={20} /></span>
            <span className="grow">
              <span className="cell-title" style={{ display: 'block' }}>
                {body?.weight != null ? <><span className="num">{fmt(body.weight)}</span> кг</> : 'Вес не указан'}
                {body?.body_fat != null && <span className="muted" style={{ fontWeight: 400 }}> · <span className="num">{fmt(body.body_fat)}</span> % жира</span>}
              </span>
              <span className="cell-sub" style={{ display: 'block' }}>Обновить замер</span>
            </span>
            <Ico.arrow size={16} className="cell-chev" />
          </button>
        </div>
      </Section>

      {adding && (
        <Sheet title="Добавить еду" onClose={closeAdd}>
          {b.BannerEl}
          <Seg value={meal} options={MEALS} onChange={setMeal} label="Приём пищи" />
          {!photoPrev ? (
            <>
              <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Что съел? Например, овсянка 100 г"
                className="field mt" maxLength={300} />
              <div className="field-row mt">
                <input value={cal} onChange={(e) => setCal(e.target.value)} placeholder="Ккал" inputMode="decimal"
                  className="field field-num" style={{ flex: '0 1 120px' }} maxLength={7}
                  onKeyDown={(e) => { if (e.key === 'Enter') log() }} />
                <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden
                  onChange={(e) => onPhoto(e.target.files?.[0])} />
                <button onClick={() => fileRef.current?.click()} disabled={photoBusy} className="btn btn-ghost grow" style={{ minHeight: 44 }}>
                  <Ico.camera size={18} /> {photoBusy ? 'Смотрю на фото…' : 'По фото'}
                </button>
              </div>
            </>
          ) : (
            <div className="mt">
              <img src={photoPrev.url} alt="Фото блюда" className="photo" />
              <div className="hstack spread mt" style={{ alignItems: 'flex-start' }}>
                <span className="wrap grow">{photoPrev.description}</span>
                {photoPrev.calories != null && <span className="num accent" style={{ flex: 'none' }}>~{fmt(photoPrev.calories)} ккал</span>}
              </div>
              {photoPrev.calories == null && (
                <input value={manualCal} onChange={(e) => setManualCal(e.target.value)}
                  placeholder="Калории вручную" inputMode="decimal" className="field field-num mt" />
              )}
              <button onClick={() => { setPhotoPrev(null); setManualCal('') }} className="btn btn-quiet mt">Другое фото</button>
            </div>
          )}
          <MainAction cfg={main} />
        </Sheet>
      )}

      {bodyOpen && (
        <Sheet title="Замер тела" onClose={() => setBodyOpen(false)}>
          {b.BannerEl}
          <div className="field-row">
            <input value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="Вес, кг" inputMode="decimal" className="field field-num" maxLength={6} />
            <input value={fat} onChange={(e) => setFat(e.target.value)} placeholder="% жира" inputMode="decimal" className="field field-num" maxLength={5} />
          </div>
          <div className="row-meta" style={{ marginTop: 6 }}>Можно указать только одно из двух.</div>
          <MainAction cfg={main} />
        </Sheet>
      )}
    </div>
  )
}
