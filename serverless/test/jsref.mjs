// Same scenario as pyref.py, run through the serverless port.
//   node --import ./loader.mjs jsref.mjs scenario.json > out.json
import { readFileSync } from 'node:fs'
import { boot, say, photo, press, state } from './harness.mjs'

const scenario = JSON.parse(readFileSync(process.argv[2], 'utf8'))
await boot()
const aiCalls = []
const script = (spec) => {
  if (spec === undefined || spec === null) return null
  const queue = Array.isArray(spec) ? [...spec] : null
  return () => (queue ? (queue.length ? queue.shift() : 'ok') : spec)
}
let ai = null
state.aiReply = (body) => {
  aiCalls.push(body)
  const r = ai ? ai() : 'ok'
  return r === null ? { error: '❌ ИИ не вернул ответ (возможно, сработала фильтрация). Попробуй ещё раз.' } : r
}
const out = []
for (const step of scenario.steps) {
  if ('ai' in step) ai = script(step.ai)
  if (step.sql) { for (const q of step.sql) state.sqlite.exec(q); continue }
  if (!('say' in step || 'photo' in step || 'press' in step)) continue
  let calls
  if ('say' in step) calls = await say(step.say)
  else if ('photo' in step) calls = await photo(step.photo)
  else calls = await press(step.press)
  out.push({ step, calls })
}
const dump = {}
for (const { name } of state.sqlite.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all()) {
  dump[name] = state.sqlite.prepare(`SELECT * FROM ${name}`).all().map(r => Object.values(r))
}
process.stdout.write(JSON.stringify({ steps: out, db: dump, ai_calls: aiCalls }))
