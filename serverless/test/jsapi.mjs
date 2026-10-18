import { readFileSync } from 'node:fs'
import { boot, state, USER } from './harness.mjs'
const calls = JSON.parse(readFileSync(process.argv[2], 'utf8'))
await boot()
state.sqlite.exec("INSERT INTO user_settings (user_id, username, first_name, timezone) VALUES (42, 'tester', 'Тест', 'Europe/Moscow')")
const api = (await import('../tgcloud/endpoints/api.js')).default
let reply = 'ok'
state.aiReply = () => (reply === null ? { error: '❌ ИИ не вернул ответ (возможно, сработала фильтрация). Попробуй ещё раз.' } : reply)
const out = []
for (const c of calls) {
  if ('ai' in c) reply = c.ai
  if (!('path' in c)) continue
  const body = 'photo' in c ? { photo_b64: '/9j/4AAQ' } : c.body
  const r = await api({ method: c.method, path: c.path, body }, { initData: { user: USER } })
  out.push({ call: c, status: r.status, body: r.body })
}
process.stdout.write(JSON.stringify(out))
