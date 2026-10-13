import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api } from './api'
import { fmt, fmtDate, Section, Spinner } from './ui'

// Daily "realized potential" out of 40 = wellbeing (avg of сон/зависание/настрой)
// + diet + training + body photo score. Days without any check-in are carried at the
// last real level and drawn dotted. Plateaus and drawbacks come from the server.

type Parts = { wellbeing: number; diet: number; training: number; body: number }
type Point = { date: string; total: number | null; filled: boolean; parts: Parts | null }
type Note = { what: string; fix: string; fallback?: boolean }
type Segment = { kind: 'drawback' | 'plateau'; start: string; end: string; from: number; to: number; level?: number; note: Note | null }
export type PotentialData = { max: number; series: Point[]; segments: Segment[] }

const PARTS: Array<[keyof Parts, string]> = [
  ['wellbeing', 'Самочувствие'], ['diet', 'Питание'], ['training', 'Тренировка'], ['body', 'Тело'],
]
const KIND: Record<Segment['kind'], string> = { drawback: 'Спад', plateau: 'Плато' }

const H = 176
const PAD = { top: 22, right: 10, bottom: 22, left: 26 }

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setW(el.clientWidth)
    const ro = new ResizeObserver(() => setW(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

const num1 = (v: number) => fmt(Math.round(v * 10) / 10)

function Chart({ data }: { data: PotentialData }) {
  const [ref, W] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const pts = data.series
  const n = pts.length
  const max = data.max
  const iw = Math.max(0, W - PAD.left - PAD.right)
  const ih = H - PAD.top - PAD.bottom
  const step = n > 1 ? iw / (n - 1) : 0
  const x = (i: number) => PAD.left + (n > 1 ? i * step : iw / 2)
  const y = (v: number) => PAD.top + ih - (v / max) * ih
  const idx = (d: string) => pts.findIndex((p) => p.date === d)

  // X labels: ~5 evenly spaced dates, always the last one.
  const every = Math.max(1, Math.ceil(n / 5))
  const xTicks = pts.map((_, i) => i).filter((i) => (n - 1 - i) % every === 0)

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.round((e.clientX - r.left - PAD.left) / (step || 1))
    const k = Math.max(0, Math.min(n - 1, i))
    setHover(pts[k]?.total == null ? null : k)
  }

  const hp = hover != null ? pts[hover] : null

  return (
    <div ref={ref} className="pc" style={{ height: H }}>
      {W > 0 && (
        <svg width={W} height={H} role="img"
          aria-label={`Реализованный потенциал по дням, из ${max}`}>
          {data.segments.map((s, k) => {
            const a = idx(s.start), b = idx(s.end)
            if (a < 0 || b < 0) return null
            const x0 = Math.max(PAD.left, x(a) - step / 2), x1 = Math.min(PAD.left + iw, x(b) + step / 2)
            return (
              <g key={k} className={`pc-band is-${s.kind}`}>
                <rect x={x0} y={PAD.top - 16} width={Math.max(4, x1 - x0)} height={ih + 16} rx={6} />
                <text x={(x0 + x1) / 2} y={PAD.top - 5} textAnchor="middle">{k + 1}</text>
              </g>
            )
          })}

          {[0, 10, 20, 30, 40].map((v) => (
            <g key={v} className="pc-grid">
              <line x1={PAD.left} x2={PAD.left + iw} y1={y(v)} y2={y(v)} />
              <text x={PAD.left - 6} y={y(v) + 3.5} textAnchor="end">{v}</text>
            </g>
          ))}
          {xTicks.map((i) => (
            <text key={i} className="pc-xlabel" x={x(i)} y={H - 6}
              textAnchor={i === 0 && n > 1 ? 'start' : i === n - 1 && n > 1 ? 'end' : 'middle'}>{fmtDate(pts[i].date)}</text>
          ))}

          {pts.map((p, i) => {
            const q = pts[i - 1]
            if (i === 0 || p.total == null || q?.total == null) return null
            return <line key={i} className={`pc-line${p.filled || q.filled ? ' is-gap' : ''}`}
              x1={x(i - 1)} y1={y(q.total)} x2={x(i)} y2={y(p.total)} />
          })}
          {pts.map((p, i) => (p.total != null && !p.filled
            ? <circle key={i} className="pc-dot" cx={x(i)} cy={y(p.total)} r={n > 20 ? 2.5 : 3.5} />
            : null))}

          {hp && hover != null && (
            <g className="pc-cross">
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + ih} />
              <circle cx={x(hover)} cy={y(hp.total!)} r={5} />
            </g>
          )}
          <rect x={0} y={0} width={W} height={H} fill="transparent"
            onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
        </svg>
      )}
      {hp && hover != null && (
        <div className="pc-tip" style={{
          left: Math.min(Math.max(x(hover) - 80, 0), Math.max(0, W - 160)),
          top: Math.max(0, Math.min(y(hp.total!) + 12, H - 120)),
        }}>
          <div className="hstack spread"><span className="muted">{fmtDate(hp.date, true)}</span><b className="num">{num1(hp.total!)}/{max}</b></div>
          {hp.filled
            ? <div className="muted" style={{ marginTop: 4 }}>Нет чек-ина — держим прошлый уровень</div>
            : PARTS.map(([k, label]) => (
              <div key={k} className="hstack spread"><span className="muted">{label}</span><span className="num">{num1(hp.parts![k])}</span></div>
            ))}
        </div>
      )}
    </div>
  )
}

export default function Potential({ data, days }: { data: PotentialData; days: number }) {
  const [segments, setSegments] = useState<Segment[]>(data.segments)
  const [notesErr, setNotesErr] = useState(false)
  const needNotes = data.segments.some((s) => !s.note)

  useEffect(() => {
    setSegments(data.segments)
    setNotesErr(false)
    if (!needNotes) return
    let live = true
    api.statsNotes(days)
      .then((r) => { if (live) setSegments(r.segments) })
      .catch(() => { if (live) setNotesErr(true) })
    return () => { live = false }
  }, [data, days])

  const real = data.series.filter((p) => p.total != null && !p.filled)
  const latest = [...data.series].reverse().find((p) => p.total != null)
  const avg = real.length ? real.reduce((a, p) => a + (p.total ?? 0), 0) / real.length : null
  const noPhoto = latest?.parts && latest.parts.body === 0

  if (!latest) return null

  return (
    <Section label="Реализованный потенциал" aux={<span className="num muted" style={{ fontSize: 12 }}>из {data.max} в день</span>}>
      <div className="panel" style={{ padding: '12px 10px 6px' }}>
        <div className="hstack" style={{ gap: 18, padding: '0 4px 6px', alignItems: 'baseline' }}>
          <div>
            <span className="label">Последний день</span>
            <div className="pc-big num">{num1(latest.total!)}<small>/{data.max}</small></div>
          </div>
          {avg != null && (
            <div>
              <span className="label">Среднее</span>
              <div className="pc-big num" style={{ color: 'var(--text-2)' }}>{num1(avg)}</div>
            </div>
          )}
        </div>
        <Chart data={{ ...data, segments }} />
        <div className="pc-legend">
          <span><i className="pc-key is-line" />день</span>
          <span><i className="pc-key is-gap" />без чек-ина</span>
          {segments.some((s) => s.kind === 'drawback') && <span><i className="pc-key is-drawback" />спад</span>}
          {segments.some((s) => s.kind === 'plateau') && <span><i className="pc-key is-plateau" />плато</span>}
        </div>
      </div>
      {noPhoto && (
        <div className="row-meta" style={{ marginTop: 8 }}>
          Тело пока 0 из 10 — пришли фото на «Обзоре», и оценка добавится к каждому дню.
        </div>
      )}

      {segments.map((s, k) => (
        <div key={`${s.kind}${s.start}`} className={`panel pc-note is-${s.kind}`}>
          <div className="hstack" style={{ gap: 8 }}>
            <span className="pc-badge num">{k + 1}</span>
            <b style={{ fontWeight: 600 }}>{KIND[s.kind]}</b>
            <span className="row-meta num" style={{ margin: 0 }}>
              {fmtDate(s.start)}–{fmtDate(s.end)} · {s.kind === 'drawback' ? `${num1(s.from)} → ${num1(s.to)}` : `≈${num1(s.level ?? s.from)}`}
            </span>
          </div>
          {s.note ? (
            <>
              <div className="pc-note-h">Что произошло</div>
              <p className="wrap">{s.note.what}</p>
              <div className="pc-note-h">Как не допустить</div>
              <p className="wrap">{s.note.fix}</p>
            </>
          ) : notesErr ? (
            <p className="muted">Не получилось получить разбор. Обнови вкладку позже.</p>
          ) : (
            <p className="muted hstack" style={{ gap: 8 }}><Spinner /> Check разбирает, что тут было…</p>
          )}
        </div>
      ))}
    </Section>
  )
}
