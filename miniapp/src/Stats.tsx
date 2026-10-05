import { useEffect, useState } from 'react'
import { api } from './api'
import { Ico, type IconName } from './icons'
import { Empty, fmt, fmtDate, LoadError, Meter, Section, Seg, Skeleton, Skeletons } from './ui'

const CATS: Array<[string, string, IconName]> = [
  ['сон', 'Сон', 'sleep'],
  ['еда', 'Еда', 'food'],
  ['активность', 'Активность', 'activity'],
  ['зависание', 'Зависание', 'idle'],
  ['настрой', 'Настрой', 'target'],
]

export default function Stats() {
  const [data, setData] = useState<any>(null)
  const [loadErr, setLoadErr] = useState<unknown>(null)
  const [days, setDays] = useState(7)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let live = true
    setData(null)
    setLoadErr(null)
    api.stats(days)
      .then((d) => { if (live) setData(d) })
      .catch((e) => { if (live) setLoadErr(e) })
    return () => { live = false }
  }, [days, attempt])

  const daily: Array<{ date: string; ratings: Record<string, number> }> = data?.daily ?? []
  // newest first — today is what you check most
  const rows = [...daily].reverse()
  const avg = CATS.map(([k]) => {
    const vals = daily.map((d) => d.ratings[k]).filter((v) => typeof v === 'number')
    return vals.length ? vals.reduce((a, v) => a + v, 0) / vals.length : null
  })

  return (
    <div>
      <Seg value={days} options={[[7, '7 дней'], [14, '14 дней'], [30, '30 дней']]} onChange={setDays} label="Период" />

      {loadErr && <div className="section"><LoadError error={loadErr} onRetry={() => setAttempt((a) => a + 1)} /></div>}
      {!data && !loadErr && <div className="section"><Skeleton h={96} /><div className="mt" /><Skeletons n={1} h={240} /></div>}

      {data && (
        <>
          <div className="panel section" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
            <div className="readout" style={{ gridColumn: '1 / -1' }}>
              <span className="label">Ранг</span>
              <div className="readout-val wrap" style={{ fontWeight: 600 }}>{data.rank?.emoji} {data.rank?.name}</div>
            </div>
            <div className="readout">
              <span className="label">Серия</span>
              <div className={`readout-val num clip${data.streak > 0 ? ' warm' : ''}`}><Ico.flame size={15} /> {fmt(data.streak ?? 0)}</div>
            </div>
            <div className="readout">
              <span className="label">Искры</span>
              <div className="readout-val num clip warm">{fmt(data.rank?.total_sparks ?? 0)}</div>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <div className="hstack spread" style={{ marginBottom: 6 }}>
                <span className="label">Тренировки за месяц</span>
                <span className="num" style={{ fontSize: 13 }}>{fmt(data.workout?.current_count ?? 0)}/{fmt(data.workout?.monthly_goal ?? 0)}</span>
              </div>
              <Meter value={data.workout?.current_count ?? 0} max={data.workout?.monthly_goal ?? 0}
                tone={(data.workout?.current_count ?? 0) >= (data.workout?.monthly_goal ?? 1) ? 'warm' : undefined} />
            </div>
          </div>

          {daily.length === 0 ? (
            <div className="section">
              <Empty icon="chart" title="За этот период оценок нет"
                text="Заполняй чек-ин на главном экране — здесь появится карта по дням." />
            </div>
          ) : (
            <Section label="Чек-ин по дням" aux={<span className="num muted" style={{ fontSize: 12 }}>{daily.length} дн.</span>}>
              <div className="panel" style={{ padding: '10px 8px', overflowX: 'auto' }}>
                <table className="heat">
                  <thead>
                    <tr>
                      <th />
                      {CATS.map(([k, label, icon]) => {
                        const Icon = Ico[icon]
                        return <th key={k} title={label} aria-label={label}><Icon size={16} /></th>
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="heat-date label">Среднее</td>
                      {avg.map((v, i) => (
                        <td key={i} className="num accent" style={{ textAlign: 'center', fontSize: 12.5, paddingBottom: 4 }}>
                          {v == null ? '–' : v.toFixed(1).replace('.', ',')}
                        </td>
                      ))}
                    </tr>
                    {rows.map((d) => (
                      <tr key={d.date}>
                        <td className="heat-date num">{fmtDate(d.date, true)}</td>
                        {CATS.map(([k]) => {
                          const v = d.ratings[k]
                          if (typeof v !== 'number') return <td key={k}><div className="heat-cell is-empty" /></td>
                          return (
                            <td key={k}>
                              <div className={`heat-cell${v >= 7 ? ' is-hi' : ''}`} title={`${v}/10`}>
                                <i style={{ opacity: 0.12 + (v / 10) * 0.88 }} />
                                <b style={{ lineHeight: '28px' }}>{v}</b>
                              </div>
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  )
}
