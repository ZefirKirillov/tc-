// Thin helpers over the platform's Bot API client, shaped like the aiogram
// calls the Python bot made.

import { api, BotApiError, InputFile } from 'sdk'
import { BACK_BUTTON_TEXT, BACK_BUTTON_CALLBACK } from './config.js'

export { api, InputFile }

// ---- keyboards ----

export const btn = (text, callback_data) => ({ text, callback_data })
export const appBtn = (text, url) => ({ text, web_app: { url } })
export const kb = (rows) => ({ inline_keyboard: rows })

const backRow = () => [btn(BACK_BUTTON_TEXT, BACK_BUTTON_CALLBACK)]

function hasBack(rows) {
  return (rows || []).some(r => (r || []).some(b => b && b.callback_data === BACK_BUTTON_CALLBACK))
}

/** keyboards/common.with_back_kb: append the universal «🔙 Назад» row. */
export function withBack(rows) {
  rows = rows || []
  if (hasBack(rows)) return rows
  return [...rows, backRow()]
}

/** keyboards/common.back_reply_keyboard */
export const backKeyboard = () => kb([backRow()])

// ---- messages ----

export async function send(chatId, text, opts = {}) {
  return api.sendMessage({ chat_id: chatId, text, ...clean(opts) })
}

export async function del(chatId, messageId) {
  if (!messageId) return
  try {
    await api.deleteMessage({ chat_id: chatId, message_id: messageId })
  } catch (e) {
    if (!(e instanceof BotApiError)) console.warn('[BOT] delete', messageId, e && e.message)
  }
}

export async function edit(chatId, messageId, text, opts = {}) {
  return api.editMessageText({ chat_id: chatId, message_id: messageId, text, ...clean(opts) })
}

export async function editMarkup(chatId, messageId, replyMarkup) {
  return api.editMessageReplyMarkup({
    chat_id: chatId, message_id: messageId,
    ...(replyMarkup ? { reply_markup: replyMarkup } : {}),
  })
}

export async function answerCb(callbackId, text, showAlert = false) {
  try {
    await api.answerCallbackQuery({
      callback_query_id: callbackId,
      ...(text ? { text } : {}),
      ...(showAlert ? { show_alert: true } : {}),
    })
  } catch { /* already answered or expired */ }
}

export async function typing(chatId) {
  try { await api.sendChatAction({ chat_id: chatId, action: 'typing' }) } catch { /* noop */ }
}

export async function sendPhoto(chatId, bytes, opts = {}) {
  return api.sendPhoto({
    chat_id: chatId,
    photo: new InputFile(bytes, 'chart.png', { type: 'image/png' }),
    ...clean(opts),
  })
}

function clean(opts) {
  const o = {}
  for (const [k, v] of Object.entries(opts)) if (v !== undefined && v !== null) o[k] = v
  return o
}

/** HTML-escape for parse_mode HTML. */
export function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#x27;')
}
