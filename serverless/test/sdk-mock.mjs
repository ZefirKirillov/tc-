// A small stand-in for the platform SDK: Bot API calls are recorded, the
// local database is an in-memory map, and fetch() serves Turso's HTTP API
// from a node:sqlite database plus a scripted AI relay.
import { DatabaseSync } from 'node:sqlite'
import { readFileSync } from 'node:fs'

export const state = {
  calls: [],          // Bot API calls: { method, params }
  nextMessageId: 1000,
  sqlite: null,
  aiReply: () => 'ok', // (body) => text | { pending: true } | { error }
  aiCalls: [],
  chartCalls: [],
  failMethods: new Set(),
}

export function resetAll() {
  state.calls = []
  state.aiCalls = []
  state.chartCalls = []
  state.failMethods = new Set()
  state.aiReply = () => 'ok'
  state.sqlite = new DatabaseSync(':memory:')
  state.sqlite.exec(readFileSync(new URL('./schema.sql', import.meta.url), 'utf8'))
  localTables.clear()
}

// ---- Bot API ----

export class BotApiError extends Error {
  constructor(method, code, description) {
    super(description)
    this.method = method; this.code = code; this.description = description; this.parameters = {}
  }
}

export class EndpointError extends Error {
  constructor(description, parameters = {}) { super(description); this.description = description; this.parameters = parameters }
}

export class InputFile {
  constructor(bytes, name, opts = {}) { this.bytes = bytes; this.name = name; this.type = opts.type }
}

export class FormData { constructor() { this.parts = [] } append(k, v) { this.parts.push([k, v]) } }

export const api = new Proxy({}, {
  get(_, method) {
    return async (params = {}) => {
      state.calls.push({ method, params })
      if (state.failMethods.has(method)) throw new BotApiError(method, 400, 'Bad Request: mocked failure')
      if (method === 'getFileContent') return new Uint8Array([0xff, 0xd8, 0xff, 1, 2, 3])
      if (method === 'getMe') return { id: 1, username: 'test_bot', first_name: 'Test' }
      if (['sendMessage', 'sendPhoto'].includes(method)) {
        const id = state.nextMessageId++
        state.calls[state.calls.length - 1].sentId = id
        return { message_id: id, chat: { id: params.chat_id, type: 'private' }, text: params.text, date: 0 }
      }
      if (method === 'editMessageText') return { message_id: params.message_id, chat: { id: params.chat_id }, text: params.text }
      return true
    }
  },
})

// ---- local db (just what lib/session.js uses) ----

const localTables = new Map()

function col(type) {
  const c = { type, name: null, pk: false }
  const chain = { primaryKey() { c.pk = true; return chain }, notNull() { return chain }, default() { return chain }, unique() { return chain }, _c: c }
  return (name) => { c.name = name; return chain }
}
export const integer = (name) => col('integer')(name)
export const text = (name) => col('text')(name)
export const json = (name) => col('json')(name)
export const real = (name) => col('real')(name)
export const boolean = (name) => col('boolean')(name)

export function table(name, cols) {
  const t = { __table: name }
  for (const [key, chain] of Object.entries(cols)) t[key] = { key, table: name, pk: chain._c.pk }
  return t
}

export const eq = (ref, val) => ({ ref, val })
export const sql = (strings, ...vals) => ({ strings, vals })

const rowsOf = (t) => { if (!localTables.has(t.__table)) localTables.set(t.__table, new Map()); return localTables.get(t.__table) }
const pkOf = (t) => Object.values(t).find(v => v && v.pk).key

export const db = {
  select() {
    return {
      from(t) {
        let cond = null
        const q = {
          where(c) { cond = c; return q },
          async get() {
            for (const r of rowsOf(t).values()) if (!cond || r[cond.ref.key] === cond.val) return structuredClone(r)
            return null
          },
          async all() { return [...rowsOf(t).values()].filter(r => !cond || r[cond.ref.key] === cond.val).map(r => structuredClone(r)) },
        }
        return q
      },
    }
  },
  insert(t) {
    return {
      values(v) {
        let conflict = null
        const run = async () => {
          const key = v[pkOf(t)]
          const rows = rowsOf(t)
          if (rows.has(key)) {
            if (!conflict) throw new Error('UNIQUE constraint failed')
            rows.set(key, { ...rows.get(key), ...structuredClone(conflict.set) })
          } else rows.set(key, structuredClone(v))
          return { rowsAffected: 1 }
        }
        const q = {
          onConflictDoUpdate(o) { conflict = o; return q },
          run,
          then(res, rej) { return run().then(res, rej) },
        }
        return q
      },
    }
  },
}
export default db

// ---- fetch: Turso pipeline + relay ----

function encodeValue(v) {
  if (v === null || v === undefined) return { type: 'null' }
  if (typeof v === 'bigint') return { type: 'integer', value: v.toString() }
  if (typeof v === 'number') return Number.isInteger(v) ? { type: 'integer', value: String(v) } : { type: 'float', value: v }
  return { type: 'text', value: String(v) }
}

function decodeArg(a) {
  if (a.type === 'null') return null
  if (a.type === 'integer') return Number(a.value)
  if (a.type === 'float') return Number(a.value)
  return a.value
}

function runStmt(stmt) {
  const db = state.sqlite
  const args = (stmt.args || []).map(decodeArg)
  const prepared = db.prepare(stmt.sql)
  const cols = prepared.columns().map(c => ({ name: c.name }))
  if (cols.length) {
    prepared.setReadBigInts(false)
    const rows = prepared.all(...args)
    return { cols, rows: rows.map(r => cols.map(c => encodeValue(r[c.name]))), affected_row_count: 0, last_insert_rowid: null }
  }
  const info = prepared.run(...args)
  return { cols: [], rows: [], affected_row_count: Number(info.changes), last_insert_rowid: String(info.lastInsertRowid) }
}

function response(status, body, headers = {}) {
  const bytes = typeof body === 'string' ? new TextEncoder().encode(body) : body
  return {
    status, ok: status >= 200 && status < 300, headers: { get: (k) => headers[k.toLowerCase()] ?? null },
    async text() { return new TextDecoder().decode(bytes) },
    async json() { return JSON.parse(new TextDecoder().decode(bytes)) },
    body: { async *[Symbol.asyncIterator]() { yield bytes } },
  }
}

export async function fetch(url, opts = {}) {
  if (url.startsWith('https://test.turso.local/v2/pipeline')) {
    const { requests } = JSON.parse(opts.body)
    const results = requests.map(r => {
      if (r.type === 'close') return { type: 'ok', response: { type: 'close' } }
      try { return { type: 'ok', response: { type: 'execute', result: runStmt(r.stmt) } } } catch (e) { return { type: 'error', error: { message: e.message } } }
    })
    return response(200, JSON.stringify({ results }))
  }
  if (url === 'https://relay.test.local/relay/generate') {
    const body = JSON.parse(opts.body)
    state.aiCalls.push(body)
    const r = state.aiReply(body)
    const lines = []
    if (r && r.pending) lines.push({ tick: 1 }, { pending: true })
    else if (r && r.error) lines.push({ done: true, text: null, error: r.error })
    else {
      if (body.stream) lines.push({ delta: String(r).slice(0, 3) }, { delta: String(r).slice(3) })
      lines.push({ done: true, text: String(r), error: null })
    }
    return response(200, lines.map(l => JSON.stringify(l)).join('\n') + '\n', { 'content-type': 'application/x-ndjson' })
  }
  if (url === 'https://relay.test.local/relay/chart') {
    state.chartCalls.push(JSON.parse(opts.body))
    return response(200, new Uint8Array([0x89, 0x50, 0x4e, 0x47]))
  }
  throw new Error(`unexpected fetch ${url}`)
}
fetch.body = { json: (o) => JSON.stringify(o) }
