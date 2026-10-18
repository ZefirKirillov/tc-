// Drive the bot like Telegram would: send a message / press a button, then
// look at the Bot API calls it made.
import { state, resetAll } from './sdk-mock.mjs'

export { state }
export const USER = { id: 42, is_bot: false, first_name: 'Тест', username: 'tester' }
const chat = { id: USER.id, type: 'private' }

let onMessage, onCallback
export async function boot() {
  resetAll()
  onMessage = (await import('../tgcloud/handlers/message.js')).default
  onCallback = (await import('../tgcloud/handlers/callback_query.js')).default
}

let updateId = 1
export async function say(text, extra = {}) {
  const before = state.calls.length
  await onMessage({ message_id: state.nextMessageId++, from: USER, chat, date: 0, text, ...extra }, { update: { update_id: updateId++ } })
  return state.calls.slice(before)
}

export async function photo(fileId = 'PHOTO1') {
  return say(undefined, { text: undefined, photo: [{ file_id: 'small', width: 90, height: 90 }, { file_id: fileId, width: 1280, height: 960 }] })
}

/** Press a button; by default on the last message that carried it. */
export async function press(data, messageId) {
  if (messageId === undefined) messageId = lastMessageWithButton(data)
  const before = state.calls.length
  await onCallback({ id: String(updateId), from: USER, data, chat_instance: '1', message: { message_id: messageId ?? 1, chat, date: 0 } },
    { update: { update_id: updateId++ } })
  return state.calls.slice(before)
}

export function buttons(markup) {
  return (markup?.inline_keyboard || []).flat()
}

export function lastMessageWithButton(data) {
  for (let i = state.calls.length - 1; i >= 0; i--) {
    const { method, params } = state.calls[i]
    if (!['sendMessage', 'editMessageText', 'editMessageReplyMarkup'].includes(method)) continue
    if (buttons(params.reply_markup).some(b => b.callback_data === data)) {
      return params.message_id ?? state.calls[i].sentId
    }
  }
  return undefined
}

/** Texts the bot sent or edited in these calls. */
export const texts = (calls) => calls.filter(c => c.method === 'sendMessage' || c.method === 'editMessageText').map(c => c.params.text)

export function sql(q, ...args) {
  return state.sqlite.prepare(q).all(...args)
}
