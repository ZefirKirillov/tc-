// A small dispatcher in the spirit of aiogram's Router: handlers are tried in
// registration order and the first whose filter matches runs. Registration
// order mirrors trackcheck/handlers/__init__.py so behaviour matches.

import { loadSession, saveSession } from './session.js'
import { answerCb, del, send } from './tg.js'
import { one, execute } from './turso.js'

const routes = { message: [], callback_query: [] }

/**
 * filter (all given keys must match):
 *   command: 'start'          — /start, /start@bot, /start payload
 *   text: '…'                 — exact text
 *   state: 'Group:name' | [..] — current FSM state
 *   photo: true               — message has a photo (or an image document)
 *   data: '…'                 — exact callback data
 *   prefix: '…'               — callback data starts with
 *   when: (c) => bool         — anything else
 */
export function onMessage(filter, fn) { routes.message.push({ filter: filter || {}, fn }) }
export function onCallback(filter, fn) { routes.callback_query.push({ filter: filter || {}, fn }) }

function commandOf(text) {
  const m = /^\/([A-Za-z0-9_]+)(?:@\w+)?(?:\s|$)/.exec(text || '')
  return m ? m[1].toLowerCase() : null
}

function matches(filter, c) {
  if (filter.state !== undefined) {
    const states = Array.isArray(filter.state) ? filter.state : [filter.state]
    if (!states.includes(c.s.getState())) return false
  }
  if (filter.command !== undefined && commandOf(c.text) !== filter.command) return false
  if (filter.text !== undefined && c.text !== filter.text) return false
  if (filter.photo && !c.photoFileId) return false
  if (filter.data !== undefined && c.data !== filter.data) return false
  if (filter.prefix !== undefined && !(c.data || '').startsWith(filter.prefix)) return false
  if (filter.when && !filter.when(c)) return false
  return true
}

function imageFileId(msg) {
  if (msg.photo && msg.photo.length) return msg.photo[msg.photo.length - 1].file_id
  const d = msg.document
  if (d && (d.mime_type || '').startsWith('image/')) return d.file_id
  return null
}

class Ctx {
  constructor(kind, payload, session) {
    this.kind = kind
    this.s = session
    if (kind === 'message') {
      this.msg = payload
      this.from = payload.from
      this.chatId = payload.chat.id
      this.text = payload.text ?? null
      this.photoFileId = imageFileId(payload)
    } else {
      this.cb = payload
      this.from = payload.from
      this.msg = payload.message || null
      this.chatId = this.msg ? this.msg.chat.id : payload.from.id
      this.data = payload.data || ''
      this.text = null
      this.photoFileId = null
    }
    this.userId = this.from.id
  }

  /** message.answer / callback.message.answer */
  reply(text, opts) { return send(this.chatId, text, opts) }

  /** callback.answer(text, show_alert) */
  answer(text, showAlert = false) {
    return this.cb ? answerCb(this.cb.id, text, showAlert) : Promise.resolve()
  }

  /** message.delete() / callback.message.delete() — errors ignored. */
  deleteMsg() {
    return this.msg ? del(this.chatId, this.msg.message_id) : Promise.resolve()
  }
}

/** notify_service.delete_last_notification: any interaction removes the last reminder. */
async function deleteLastNotification(userId) {
  try {
    const row = await one('SELECT notify_msg_id FROM user_settings WHERE user_id = ?', [userId])
    if (row && row.notify_msg_id) {
      await del(userId, row.notify_msg_id)
      await execute('UPDATE user_settings SET notify_msg_id = NULL WHERE user_id = ? AND notify_msg_id = ?',
        [userId, row.notify_msg_id])
    }
  } catch (e) {
    console.warn('[NOTIFY] cleanup', e && e.message)
  }
}

export async function dispatch(kind, payload) {
  if (!payload.from || payload.from.is_bot) return
  if (kind === 'message' && payload.chat.type !== 'private') return
  const session = await loadSession(payload.from.id)
  const c = new Ctx(kind, payload, session)

  // Reminders are cleaned up alongside the handler, not before it — one Turso
  // round trip in parallel instead of in front of every button press.
  const cleanup = deleteLastNotification(c.userId)
  if (kind === 'callback_query') await c.answer()
  for (const [chatId, msgId] of session.takeLater()) await del(chatId, msgId)

  try {
    const route = routes[kind].find(r => matches(r.filter, c))
    if (route) await route.fn(c)
  } catch (e) {
    console.error(`[BOT] ${kind} handler failed`, e)
  } finally {
    await cleanup
    try { await saveSession(session) } catch (e) { console.error('[BOT] session save failed', e) }
  }
}
