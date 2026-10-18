// Mini App API through the endpoint, against the same local database.
import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { boot, say, press, state, sql, USER } from './harness.mjs'

let api
const call = async (method, path, body) => (await api({ method, path, body }, { initData: { user: USER } }))

beforeEach(async () => {
  await boot()
  await say('/start'); await press('ws_start'); await press('tz:Europe/Moscow:onboarding')
  api = (await import('../tgcloud/endpoints/api.js')).default
})

test('me / ratings / tasks', async () => {
  let r = await call('GET', '/api/me')
  assert.equal(r.status, 200)
  assert.equal(r.body.data.name, 'Тест')
  r = await call('POST', '/api/ratings', { category: 'еда', rating: 5 })
  assert.equal(r.body.error, 'auto_category')
  r = await call('POST', '/api/ratings', { category: 'сон', rating: 8 })
  assert.deepEqual(r.body.data.ratings, { 'сон': 8 })
  r = await call('POST', '/api/tasks', { title: 'Задача', is_priority: true, deadline: '2030-01-01', repeat_days: [0, 7, '3'] })
  assert.equal(r.body.ok, true)
  assert.equal(sql('SELECT repeat_days FROM tasks')[0].repeat_days, '0,3')
  r = await call('POST', '/api/tasks/1/done', {})
  r = await call('DELETE', '/api/tasks/1')
  assert.equal(r.body.data.deleted, true)
  r = await call('GET', '/api/nope')
  assert.equal(r.status, 404)
})

test('diet: profile, estimate, log, photo', async () => {
  let r = await call('POST', '/api/diet/estimate', { description: 'суп' })
  assert.equal(r.body.error, 'no_diet_profile')
  r = await call('POST', '/api/diet/profile', { weight: 80, height: 180, age: 30, gender: 'male', activity: 1.55, goal: 'loss', change: 5, days: 90 })
  assert.equal(r.body.data.saved, true)
  state.aiReply = () => '450 35 12 50'
  r = await call('POST', '/api/diet/estimate', { description: 'гречка' })
  assert.deepEqual(r.body.data, { calories: 450, protein: 35, fat: 12, carbs: 50 })
  r = await call('POST', '/api/diet/log', { description: 'гречка', calories: 450, protein: 35, fat: 12, carbs: 50, meal: 'Обед' })
  assert.equal(r.body.data.today_calories, 450)
  assert.ok(sql("SELECT * FROM ratings WHERE category = 'еда'").length === 1, 'diet rating synced')
  state.aiReply = () => 'суп 300 12 14 30'
  r = await call('POST', '/api/diet/photo', { photo_b64: '/9j/AAAA' })
  assert.equal(r.body.data.description, 'суп')
  state.aiReply = () => ({ pending: true })
  r = await call('POST', '/api/diet/photo', { photo_b64: '/9j/AAAA' })
  assert.equal(r.body.error, 'ai_pending')
})

test('workout: generate, save, start, log, finish, history', async () => {
  const days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
  const plan = { cycle_weeks: 1, week_1: Object.fromEntries(days.map(d => [d, [{ exercise: 'Жим', sets: 3, reps: '8', weight: 60 }]])) }
  state.aiReply = () => JSON.stringify(plan)
  let r = await call('POST', '/api/workout/generate', { goal: 'Сила', level: 'Средний', days: 3 })
  assert.deepEqual(r.body.data.plan, plan)
  r = await call('POST', '/api/workout/plan', { plan, mode: 'ai', goal: 'Сила', level: 'Средний', days: 3 })
  r = await call('GET', '/api/workout')
  assert.equal(r.body.data.today_exercises.length, 1)
  r = await call('POST', '/api/workout/start', {})
  const sid = r.body.data.session_id
  r = await call('POST', '/api/workout/log', { session_id: sid, exercise: plan.week_1.monday[0], action: 'done' })
  assert.deepEqual(r.body.data.raise, { kind: 'plan', name: 'Жим', weight: 60 })
  r = await call('POST', '/api/workout/raise', { target: r.body.data.raise, increment: '2,5' })
  assert.equal(r.body.data.weight, 62.5)
  r = await call('POST', '/api/workout/finish', { session_id: sid })
  assert.equal(r.body.data.done, 1)
  assert.equal(r.body.data.spark_awarded, true)
  r = await call('GET', '/api/workout/history?limit=5')
  assert.equal(r.body.data[0].status, 'done')
  r = await call('GET', '/api/stats?days=7')
  assert.equal(r.body.data.potential.max, 40)
  r = await call('GET', '/api/stats/notes?days=7')
  assert.ok(Array.isArray(r.body.data.segments))
})

test('ai ask: answer saved, pending reported', async () => {
  state.aiReply = () => '**Да**, можно.'
  let r = await call('POST', '/api/ai/ask', { question: 'Можно ли?' })
  assert.equal(r.body.data.answer, 'Да, можно.')
  r = await call('GET', '/api/ai/last')
  assert.equal(r.body.data.answer, 'Да, можно.')
  state.aiReply = () => ({ pending: true })
  r = await call('POST', '/api/ai/advice', {})
  assert.equal(r.status, 503)
  assert.match(r.body.message, /⏳/)
})
