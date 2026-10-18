// Behaviour specific to the serverless port (no Python counterpart to diff against).
//   node --test --import ./loader.mjs serverless.test.mjs
import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { boot, say, press, photo, texts, state, sql } from './harness.mjs'

async function onboard() {
  await say('/start'); await press('ws_start'); await press('tz:Europe/Moscow:onboarding')
}

beforeEach(async () => { await boot(); await onboard() })

test('AI still running: the user gets «⏳» and the retry joins the same relay job', async () => {
  await press('menu_ai')
  state.aiReply = () => ({ pending: true })
  let r = await say('Сколько белка в день?')
  assert.match(texts(r).at(-1), /⏳ ИИ ещё думает/)
  const firstKey = state.aiCalls.at(-1).key
  state.aiReply = () => '1.6–2 г на кг веса.'
  r = await press('retry_ai:ai_question')
  assert.equal(state.aiCalls.at(-1).key, firstKey, 'retry must reuse the relay job key')
  assert.match(texts(r).at(-1), /1\.6–2 г на кг веса/)
})

test('relay down: a friendly error, nothing thrown', async () => {
  await press('menu_ai')
  state.aiReply = () => { throw new Error('ECONNREFUSED') }
  const r = await say('Привет, как дела?')
  assert.ok(texts(r).some(t => /❌/.test(t)))
})

test('any interaction removes the last reminder sent by the worker', async () => {
  sql("UPDATE user_settings SET notify_msg_id = 777 WHERE user_id = 42")
  const r = await press('menu_tasks')
  assert.ok(r.some(c => c.method === 'deleteMessage' && c.params.message_id === 777))
  assert.equal(sql('SELECT notify_msg_id FROM user_settings WHERE user_id = 42')[0].notify_msg_id, null)
})

test('temporary messages are deleted on the next interaction (no timers here)', async () => {
  await press('menu_tasks'); await press('task_new'); await say('Позвонить'); await press('task_type_once')
  await press('task_priority_no')
  let r = await press('task_deadline_no')
  const confirm = r.find(c => c.method === 'sendMessage' && /Задача добавлена/.test(c.params.text))
  assert.ok(confirm)
  r = await press('nav_back')
  assert.ok(r.some(c => c.method === 'deleteMessage' && c.params.message_id === confirm.sentId))
})

test('monthly review parses the model JSON (the Python bot crashed here)', async () => {
  const days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
  const plan = { cycle_weeks: 1, week_1: Object.fromEntries(days.map(d => [d, [{ exercise: 'Жим лёжа', sets: 3, reps: '8', weight: 60 }]])) }
  await press('menu_workouts'); await press('menu_workout_add'); await press('wp_mode_manual')
  state.aiReply = () => JSON.stringify(plan)
  await say('план'); await press('wp_plan_accept')
  state.aiReply = () => JSON.stringify({ changes: [{ day: 'monday', week: 'week_1', old_exercise: 'Жим лёжа', new_exercise: 'Жим гантелей', reason: 'разнообразие' }], no_changes_needed: false })
  await press('menu_workouts'); await press('menu_workout_manage')
  await press('wp_settings', 1)
  let r = await press('wp_monthly_review', 1)
  assert.match(texts(r).at(-1), /1\. Жим лёжа → Жим гантелей/)
  r = await say('1')
  assert.match(texts(r).at(-1), /Принято: Жим лёжа → Жим гантелей/)
  const saved = JSON.parse(sql('SELECT plan_json FROM ai_workout_plan')[0].plan_json)
  assert.equal(saved.week_1.monday[0].exercise, 'Жим гантелей')
})

test('photos are re-downloaded by file_id on retry, not kept in the session', async () => {
  await press('menu_workouts'); await press('menu_photo_analysis')
  state.aiReply = () => null
  await photo('BODYX')
  const session = JSON.stringify([...(await import('./sdk-mock.mjs')).state.calls])
  assert.ok(!/base64/.test(session))
  state.aiReply = () => JSON.stringify({ score: 6, summary: 'ok', strengths: [], weaknesses: [] })
  const r = await press('retry_ai:photo_analysis')
  assert.ok(r.some(c => c.method === 'getFileContent' && c.params === 'BODYX' || c.params?.file_id === 'BODYX'))
  assert.match(texts(r).at(-1), /Оценка тела: 6\/10/)
})

test('group chats and other bots are ignored', async () => {
  const before = state.calls.length
  const { default: onMessage } = await import('../tgcloud/handlers/message.js')
  await onMessage({ message_id: 1, from: { id: 5, is_bot: false, first_name: 'X' }, chat: { id: -100, type: 'group' }, text: '/start' })
  await onMessage({ message_id: 2, from: { id: 6, is_bot: true, first_name: 'B' }, chat: { id: 6, type: 'private' }, text: '/start' })
  assert.equal(state.calls.length, before)
})

test('deleting an exercise asks Да/Нет (the Python bot showed «Пропустить →» here)', async () => {
  await press('menu_workouts'); await press('workout_manage'); await press('w_cat_new'); await say('Спина')
  await press('cat_type_strength'); await press('w_manage_cat_1'); await press('w_manage_exercises_1')
  await press('w_ex_new_1'); await say('Тяга'); await press('nav_back')
  let r = await press('w_ex_delete_1', 1)
  const kb = r.find(c => c.method === 'sendMessage').params.reply_markup.inline_keyboard.flat().map(b => b.callback_data)
  assert.deepEqual(kb, ['w_ex_delete_yes', 'workout_manage', 'nav_back'])
  r = await press('w_ex_delete_yes')
  assert.equal(sql('SELECT COUNT(*) AS n FROM exercises')[0].n, 0)
})
