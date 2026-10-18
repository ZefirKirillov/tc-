// trackcheck/utils/bot_helpers.py

import { del, send } from '../tg.js'

const PRESERVE = ['photo_analysis_result', 'photo_user', 'body_fat_measurements', 'body_fat_result']

/** Delete every temp message except the ones worth keeping (AI answers, photo results). */
export async function deleteTempMessages(c, keepAi = true) {
  const temps = c.s.temps
  const keep = new Set(PRESERVE)
  if (keepAi) { keep.add('ai_response'); keep.add('ai_advisor') }
  for (const [key, msgId] of Object.entries(temps)) {
    if (keep.has(key)) continue
    if (typeof msgId === 'number') await del(c.chatId, msgId)
    delete temps[key]
  }
}

/**
 * send_temp_message / delete_message_after_delay / send_spark_animation: there
 * are no timers here, so the message goes away on the user's next interaction.
 */
export async function sendTemp(c, text, opts) {
  const m = await send(c.chatId, text, opts)
  c.s.deleteLater(c.chatId, m.message_id)
  return m
}

export async function sendSparkAnimation(c, text) {
  await sendTemp(c, '✨')
  await sendTemp(c, text)
}
