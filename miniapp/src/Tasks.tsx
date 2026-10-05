import { useEffect, useState } from 'react'
import { api, keep, peek } from './api'
import { Ico } from './icons'
import MainAction from './MainAction'
import { haptic, hapticSelect, notifyOk } from './tg'
import { Confirm, Empty, fmtDate, LoadError, Section, Skeletons, useBanner } from './ui'

type Task = { id: number; title: string; is_priority: boolean; deadline: string | null; repeat_days: string | null; is_done: boolean }

const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export default function Tasks() {
  const b = useBanner()
  const [tasks, setTasks] = useState<Task[] | null>(() => peek('tasks') ?? null)
  const [loadErr, setLoadErr] = useState<unknown>(null)
  const [title, setTitle] = useState('')
  const [prio, setPrio] = useState(false)
  const [deadline, setDeadline] = useState('')
  const [repeat, setRepeat] = useState<Set<number>>(new Set())
  const [showOpts, setShowOpts] = useState(false)
  const [busy, setBusy] = useState(false)
  const [doing, setDoing] = useState<number | null>(null)
  const [delId, setDelId] = useState<number | null>(null)

  async function load() {
    try { setTasks(keep('tasks', await api.tasks())); setLoadErr(null) }
    catch (e) { if (tasks) b.setErr(e); else setLoadErr(e) }
  }
  useEffect(() => { load() }, [])

  async function add() {
    if (!title.trim()) { b.setErr('Введи название задачи.'); return }
    setBusy(true)
    try {
      await api.addTask(title.trim(), prio, deadline || null, repeat.size ? [...repeat] : null)
      setTitle(''); setPrio(false); setDeadline(''); setRepeat(new Set()); setShowOpts(false)
      notifyOk()
      await load()
    } catch (e) { b.setErr(e) } finally { setBusy(false) }
  }

  async function done(id: number) {
    setDoing(id)
    try { await api.doneTask(id); haptic(); notifyOk(); await load() }
    catch (e) { b.setErr(e) } finally { setDoing(null) }
  }

  async function del() {
    if (delId == null) return
    const id = delId
    setDelId(null)
    try { await api.deleteTask(id); haptic(); await load() }
    catch (e) { b.setErr(e) }
  }

  function toggleDay(d: number) {
    hapticSelect()
    const n = new Set(repeat)
    n.has(d) ? n.delete(d) : n.add(d)
    setRepeat(n)
  }

  const optsCount = (prio ? 1 : 0) + (deadline ? 1 : 0) + (repeat.size ? 1 : 0)

  if (!tasks) {
    if (loadErr) return <LoadError error={loadErr} onRetry={() => { setLoadErr(null); load() }} />
    return <div><Skeletons n={1} h={48} /><div className="mt" /><Skeletons n={4} h={56} /></div>
  }

  const open = tasks.filter((t) => !t.is_done)
  const closed = tasks.filter((t) => t.is_done)

  const renderTask = (t: Task) => (
    <div key={t.id} className="row" style={{ alignItems: 'flex-start', opacity: t.is_done ? 0.55 : 1 }}>
      <button className={`check${t.is_done ? ' is-on' : ''}`} role="checkbox" aria-checked={t.is_done}
        aria-label={t.is_done ? 'Выполнена' : 'Отметить выполненной'}
        disabled={t.is_done || doing === t.id} onClick={() => done(t.id)} style={{ marginTop: 1 }}>
        <Ico.check size={16} />
      </button>
      <div className="grow wrap">
        <div style={{ textDecoration: t.is_done ? 'line-through' : undefined }}>
          {t.is_priority && <Ico.flame size={15} className="warm" />} {t.title}
        </div>
        {(t.deadline || t.repeat_days) && (
          <div className="row-meta hstack" style={{ gap: 10, flexWrap: 'wrap' }}>
            {t.deadline && <span className="hstack" style={{ gap: 4 }}><Ico.clock size={13} /><span className="num">{fmtDate(t.deadline)}</span></span>}
            {t.repeat_days && (
              <span className="hstack" style={{ gap: 4 }}>
                <Ico.repeat size={13} />{t.repeat_days.split(',').map((d) => WD[parseInt(d)] ?? d).join(' ')}
              </span>
            )}
          </div>
        )}
      </div>
      <button onClick={() => setDelId(t.id)} className="btn btn-quiet btn-sm btn-icon" aria-label="Удалить задачу">
        <Ico.trash size={17} />
      </button>
    </div>
  )

  return (
    <div>
      {b.BannerEl}

      <div className="field-row">
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Новая задача…"
          className="field" maxLength={200} onKeyDown={(e) => { if (e.key === 'Enter' && title.trim()) add() }} />
        <button onClick={() => { hapticSelect(); setShowOpts(!showOpts) }} className={`btn btn-ghost btn-icon${optsCount ? ' accent' : ''}`}
          aria-expanded={showOpts} aria-label="Параметры задачи" style={{ minHeight: 44 }}>
          {optsCount ? <span className="num">{optsCount}</span> : <Ico.tune size={18} />}
        </button>
      </div>

      {showOpts && (
        <div className="panel mt vstack" style={{ gap: 12 }}>
          <div className="hstack spread">
            <button onClick={() => { hapticSelect(); setPrio(!prio) }} className={`chip${prio ? ' is-on' : ''}`}
              style={prio ? { color: 'var(--warm)', borderColor: 'var(--warm)', background: 'var(--warm-soft)' } : undefined}>
              <Ico.flame size={14} /> Приоритет
            </button>
            <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} className="field field-num"
              style={{ width: 'auto', minHeight: 36, padding: '4px 8px', fontSize: 14 }} aria-label="Дедлайн" />
          </div>
          <div>
            <div className="label" style={{ marginBottom: 6 }}>Повтор</div>
            <div className="chips">{WD.map((w, i) => (
              <button key={i} onClick={() => toggleDay(i)} className={`chip grow${repeat.has(i) ? ' is-on' : ''}`}>{w}</button>
            ))}</div>
          </div>
        </div>
      )}

      <MainAction cfg={title.trim() ? { text: 'Добавить задачу', onClick: add, busy } : null} />

      {tasks.length === 0 ? (
        <div className="section">
          <Empty icon="tasks" title="Задач пока нет" text="Добавь первую — дедлайн и повтор настраиваются кнопкой справа от поля." />
        </div>
      ) : (
        <>
          {open.length > 0 && (
            <Section label="Активные" aux={<span className="num muted" style={{ fontSize: 12 }}>{open.length}</span>}>
              <div className="rows">{open.map(renderTask)}</div>
            </Section>
          )}
          {open.length === 0 && (
            <div className="section"><Empty icon="check" title="Всё сделано" text="Активных задач не осталось." /></div>
          )}
          {closed.length > 0 && (
            <Section label="Выполнены" aux={<span className="num muted" style={{ fontSize: 12 }}>{closed.length}</span>}>
              <div className="rows">{closed.map(renderTask)}</div>
            </Section>
          )}
        </>
      )}

      {delId != null && (
        <Confirm title="Удалить задачу?" body="Это действие нельзя отменить." danger
          okLabel="Удалить" onOk={del} onCancel={() => setDelId(null)} />
      )}
    </div>
  )
}
