// Turso (libSQL) over its HTTP API — the bot's durable data stays in the same
// database the Python bot used. Each call is one HTTPS round trip; `batch()`
// sends several statements in one.

import { fetch } from 'sdk'
import { TURSO_DATABASE_URL, TURSO_AUTH_TOKEN } from './secrets.js'

const BASE = TURSO_DATABASE_URL.replace(/^libsql:\/\//, 'https://')

function encodeArg(v) {
  if (v === null || v === undefined) return { type: 'null' }
  if (typeof v === 'boolean') return { type: 'integer', value: v ? '1' : '0' }
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return { type: 'integer', value: String(v) }
    return { type: 'float', value: v }
  }
  if (typeof v === 'bigint') return { type: 'integer', value: v.toString() }
  return { type: 'text', value: String(v) }
}

function decodeValue(v) {
  switch (v.type) {
    case 'null': return null
    case 'integer': return Number(v.value)
    case 'float': return Number(v.value)
    case 'text': return v.value
    case 'blob': return v.base64
    default: return v.value ?? null
  }
}

export class DbError extends Error {
  constructor(message, code) {
    super(message)
    this.code = code
  }
}

/** True for a UNIQUE-constraint violation (duplicate insert). */
export function isUniqueViolation(e) {
  const msg = String((e && e.message) || e).toUpperCase()
  return msg.includes('UNIQUE') && msg.includes('CONSTRAINT')
}

function toResult(r) {
  const cols = (r.cols || []).map(c => c.name)
  const rows = (r.rows || []).map(raw => {
    const vals = raw.map(decodeValue)
    const obj = {}
    cols.forEach((c, i) => { obj[c] = vals[i] })
    // Positional access too (Python code often unpacks rows as tuples).
    Object.defineProperty(obj, '$', { value: vals, enumerable: false })
    return obj
  })
  return {
    rows,
    columns: cols,
    rowsAffected: r.affected_row_count || 0,
    lastInsertRowid: r.last_insert_rowid == null ? null : Number(r.last_insert_rowid),
  }
}

async function pipeline(stmts) {
  const requests = stmts.map(s => ({
    type: 'execute',
    stmt: { sql: s.sql, args: (s.args || []).map(encodeArg) },
  }))
  requests.push({ type: 'close' })
  const res = await fetch(`${BASE}/v2/pipeline`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${TURSO_AUTH_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ requests }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new DbError(`turso http ${res.status}: ${body.slice(0, 300)}`, `http_${res.status}`)
  }
  const data = await res.json()
  return data.results.slice(0, stmts.length).map(r => {
    if (r.type !== 'ok') {
      const err = r.error || {}
      throw new DbError(err.message || 'turso error', err.code)
    }
    return toResult(r.response.result)
  })
}

/** Run one statement → { rows, columns, rowsAffected, lastInsertRowid }. */
export async function execute(sql, args = []) {
  const [r] = await pipeline([{ sql, args }])
  return r
}

/** Several statements in one round trip (not a transaction). */
export async function batch(stmts) {
  if (!stmts.length) return []
  return pipeline(stmts)
}

/** First row or null. */
export async function one(sql, args = []) {
  return (await execute(sql, args)).rows[0] || null
}

/** All rows. */
export async function all(sql, args = []) {
  return (await execute(sql, args)).rows
}
