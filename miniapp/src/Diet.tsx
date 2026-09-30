import { useEffect, useRef, useState } from 'react'
import { api, haptic, notifyOk } from './api'
import { s } from './styles'
import { Skeletons, useBanner } from './ui'

export default function Diet() {
  const b = useBanner()
  const [data, setData] = useState<any>(null)
  const [desc, setDesc] = useState('')
  const [cal, setCal] = useState('')
  const [meal, setMeal] = useState('Еда')
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoPrev, setPhotoPrev] = useState<{ url: string; description: string; calories: number | null } | null>(null)
  const [manualCal, setManualCal] = useState('')
  const [body, setBody] = useState<any>(null)
  const [weight, setWeight] = useState('')
  const [fat, setFat] = useState('')
  const [bodyBusy, setBodyBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function load() {
    try {
      const [d, bd] = await Promise.all([api.diet(), api.body().catch(() => null)])
      setData(d)
      setBody(bd)
    } catch (e) { b.setErr(e) }
  }
  useEffect(() => { load() }, [])

  async function log() {
    const calories = parseFloat(cal.replace(',', '.'))
    if (!desc.trim() || !(calories > 0)) { b.setErr('Опиши блюдо и укажи калории.'); return }
    try {
      await api.logFood(desc.trim(), calories, meal)
      setDesc(''); setCal('')
      haptic(); notifyOk()
      b.setOk('Записано!')
      await load()
    } catch (e) { b.setErr(e) }
  }

  async function onPhoto(file: File | undefined) {
    if (!file) return
    if (file.size > 5 * 1024 * 1024) { b.setErr('Фото слишком большое (макс 5 МБ) 📸'); return }
    setPhotoBusy(true)
    b.clear()
    try {
      const r = await api.dietPhoto(file)
      setPhotoPrev({ url: URL.createObjectURL(file), description: r.description, calories: r.calories })
      haptic()
      if (r.needs_manual) b.setErr('Блюдо распознано, но калории оценить не удалось — введи вручную.')
    } catch (e) { b.setErr(e) } finally { setPhotoBusy(false) }
  }

  async function confirmPhoto() {
    if (!photoPrev) return
    const calories = photoPrev.calories ?? parseFloat(manualCal.replace(',', '.'))
    if (!(calories > 0)) { b.setErr('Укажи калории числом.'); return }
    try {
      await api.logFood(photoPrev.description, calories, meal)
      setPhotoPrev(null); setManualCal('')
      if (fileRef.current) fileRef.current.value = ''
      notifyOk()
      b.setOk('Записано!')
      await load()
    } catch (e) { b.setErr(e) }
  }

  async function saveBody() {
    const w = weight.trim() ? parseFloat(weight.replace(',', '.')) : null
    const f = fat.trim() ? parseFloat(fat.replace(',', '.')) : null
    if (w === null && f === null) return
    setBodyBusy(true)
    try {
      await api.saveBody(w, f)
      setWeight(''); setFat('')
      notifyOk()
      b.setOk('Сохранено!')
      await load()
    } catch (e) { b.setErr(e) } finally { setBodyBusy(false) }
  }

  if (!data) return <div><h2 style={s.h}>🍽 Диета</h2><Skeletons /></div>
  const goal = data.profile?.daily_calories ?? 0
  const eaten = Math.round(data.today_calories ?? 0)
  const pct = goal > 0 ? Math.min(100, Math.round((eaten / goal) * 100)) : 0

  return (
    <div>
      <h2 style={s.h}>🍽 Диета</h2>
      {b.BannerEl}
      {data.profile
        ? <p style={s.sub}>{eaten}/{Math.round(goal)} ккал ({pct}%)</p>
        : <p style={s.sub}>Диета не настроена в боте — логирование всё равно работает.</p>}
      <div style={{ background: 'rgba(167,139,250,0.18)', borderRadius: 8, height: 10, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: 'linear-gradient(90deg, #8b5cf6, #22d3ee)', boxShadow: '0 0 12px rgba(139,92,246,0.8)' }} />
      </div>

      <div style={s.card}>
        <div style={s.row}>
          {['Завтрак', 'Обед', 'Ужин', 'Еда'].map((m) => (
            <button key={m} onClick={() => { setMeal(m); haptic() }} style={meal === m ? s.btnActive : s.btnSm}>{m}</button>
          ))}
        </div>
        <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Что съел? (овсянка 100г)"
          style={{ ...s.input, marginTop: 8 }} maxLength={300} />
        <div style={{ ...s.row, marginTop: 8, marginBottom: 0 }}>
          <input value={cal} onChange={(e) => setCal(e.target.value)} placeholder="Ккал" inputMode="decimal"
            style={s.inputSm} />
          <button onClick={log} style={s.primary}>+ Записать</button>
        </div>
        <div style={{ ...s.row, marginTop: 8, marginBottom: 0 }}>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" style={{ display: 'none' }}
            onChange={(e) => onPhoto(e.target.files?.[0])} />
          <button onClick={() => fileRef.current?.click()} disabled={photoBusy} style={s.btnSm}>
            {photoBusy ? 'Анализирую фото…' : '📸 Фото еды'}
          </button>
        </div>
      </div>

      {photoPrev && (
        <div style={s.card}>
          <img src={photoPrev.url} alt="еда" style={{ width: '100%', borderRadius: 12 }} />
          <p style={s.sub}>{photoPrev.description}{photoPrev.calories ? ` · ~${photoPrev.calories} ккал` : ''}</p>
          {photoPrev.calories == null && (
            <input value={manualCal} onChange={(e) => setManualCal(e.target.value)}
              placeholder="Калории вручную" inputMode="decimal" style={s.input} />
          )}
          <div style={{ ...s.row, marginTop: 8, marginBottom: 0 }}>
            <button onClick={() => { setPhotoPrev(null); setManualCal('') }} style={s.btnSm}>Отмена</button>
            <button onClick={confirmPhoto} style={s.primary}>✅ Подтвердить</button>
          </div>
        </div>
      )}

      {(data.today_log ?? []).map((e: any, i: number) => (
        <div key={i} style={s.card}>
          <div style={s.row}><span>{e.meal}: {e.description}</span><b>{Math.round(e.calories)}</b></div>
        </div>
      ))}

      <div style={s.card}>
        <p style={s.sub}>⚖️ Тело {(body?.weight != null) && `· ${body.weight} кг`} {(body?.body_fat != null) && `· ${body.body_fat}% жира`}</p>
        <div style={{ ...s.row, marginBottom: 0 }}>
          <input value={weight} onChange={(e) => setWeight(e.target.value)} placeholder="Вес, кг" inputMode="decimal" style={s.inputSm} />
          <input value={fat} onChange={(e) => setFat(e.target.value)} placeholder="% жира" inputMode="decimal" style={s.inputSm} />
          <button onClick={saveBody} disabled={bodyBusy} style={s.primary}>✓</button>
        </div>
      </div>
    </div>
  )
}
