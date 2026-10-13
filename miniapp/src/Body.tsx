import { useEffect, useRef, useState } from 'react'
import { api, keep, peek } from './api'
import { Ico } from './icons'
import { haptic } from './tg'
import { fmtDate, Sheet, Spinner, useBanner } from './ui'

export type BodyScore = {
  date: string
  score: number
  summary: string
  strengths: string[]
  weaknesses: Array<{ spot: string; fix: string }>
}

/** Body score from a photo: 1–10, strong and weak spots, what to do. Counts toward
 *  the daily potential (Прогресс) until the next photo. */
export default function BodySheet({ onClose, onSaved }: { onClose: () => void; onSaved: (r: BodyScore) => void }) {
  const b = useBanner()
  const fileRef = useRef<HTMLInputElement>(null)
  const [last, setLast] = useState<BodyScore | null | undefined>(() => peek('body-score'))
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)

  useEffect(() => {
    api.bodyScore().then((d) => setLast(keep('body-score', d))).catch((e) => { setLast(null); b.setErr(e) })
  }, [])

  async function onPhoto(file: File | undefined) {
    if (!file) return
    if (file.size > 5 * 1024 * 1024) { b.setErr('Фото слишком большое (макс. 5 МБ).'); return }
    setBusy(true)
    setPreview(URL.createObjectURL(file))
    b.clear()
    try {
      const r: BodyScore = await api.bodyScorePhoto(file)
      setLast(keep('body-score', r))
      onSaved(r)
      haptic('medium')
    } catch (e) { b.setErr(e); setPreview(null) } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <Sheet title="Оценка тела" onClose={onClose}>
      {b.BannerEl}
      {preview && <img src={preview} alt="Твоё фото" className="photo" style={{ marginBottom: 12 }} />}

      {busy ? (
        <div className="muted hstack" style={{ gap: 8, padding: '8px 0' }}><Spinner fallback={<Ico.body size={18} />} /> Check смотрит на фото…</div>
      ) : last === undefined ? (
        <div className="muted hstack" style={{ gap: 8, padding: '8px 0' }}><Spinner /> Загрузка…</div>
      ) : last ? (
        <div>
          <div className="hstack spread" style={{ alignItems: 'baseline' }}>
            <div className="w-score num">{last.score}<small>/10</small></div>
            <span className="row-meta num">фото от {fmtDate(last.date)}</span>
          </div>
          {last.summary && <p className="wrap" style={{ margin: '10px 0 0' }}>{last.summary}</p>}
          {last.strengths.length > 0 && (
            <div className="mt">
              <div className="label">Сильные стороны</div>
              <ul className="body-list">
                {last.strengths.map((s, i) => <li key={i}><Ico.check size={16} className="accent" /><span className="wrap">{s}</span></li>)}
              </ul>
            </div>
          )}
          {last.weaknesses.length > 0 && (
            <div className="mt">
              <div className="label">Над чем работать</div>
              <ul className="body-list">
                {last.weaknesses.map((w, i) => (
                  <li key={i}><Ico.target size={16} className="warm" />
                    <span className="wrap"><b style={{ fontWeight: 600 }}>{w.spot}</b>{w.fix && <span className="muted"> — {w.fix}</span>}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <p className="muted wrap" style={{ margin: 0 }}>
          Пришли фото в полный рост или по пояс — Check оценит тело из 10, назовёт сильные и слабые места и что с ними делать.
        </p>
      )}

      <div className="row-meta" style={{ marginTop: 16 }}>Оценка идёт в «реализованный потенциал» на вкладке «Прогресс» — до следующего фото.</div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => onPhoto(e.target.files?.[0])} />
      <button onClick={() => fileRef.current?.click()} disabled={busy} className="btn btn-primary btn-block mt" style={{ minHeight: 48 }}>
        <Ico.camera size={18} /> {last ? 'Новое фото' : 'Отправить фото'}
      </button>
    </Sheet>
  )
}
