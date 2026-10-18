// trackcheck/handlers/notify.py — reminder mute button and on/off toggle.
// Reminders themselves are sent by the Render worker (notify_service.py).

import { onCallback } from '../router.js'
import { execute } from '../turso.js'
import { editMarkup } from '../tg.js'
import { userNow, addDays } from '../dates.js'
import { notifySettingsKeyboard } from './keyboards.js'
import { isNotifyEnabled } from './stats.js'
import { sendTemp } from './helpers.js'

/** mute_until_morning: silent until 08:00 user time (naive ISO in the user's tz). */
async function muteUntilMorning(userId) {
  const now = await userNow(userId)
  const day = now.hour >= 8 ? addDays(now.date, 1) : now.date
  await execute(`INSERT INTO user_settings (user_id, notify_muted_until) VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET notify_muted_until = excluded.notify_muted_until`, [userId, `${day}T08:00:00`])
}

async function setNotifyEnabled(userId, enabled) {
  await execute(`INSERT INTO user_settings (user_id, notify_enabled) VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET notify_enabled = excluded.notify_enabled`, [userId, enabled ? 1 : 0])
}

export function register() {
  onCallback({ data: 'notify_mute' }, async (c) => {
    await muteUntilMorning(c.userId)
    // The router already removed the reminder (any interaction does).
    try { await sendTemp(c, '🔕 Хорошо, до 08:00 не побеспокою.') } catch { /* noop */ }
    await c.answer('До утра тихо 🤫')
  })
  onCallback({ data: 'notify_toggle' }, async (c) => {
    const next = !(await isNotifyEnabled(c.userId))
    await setNotifyEnabled(c.userId, next)
    try { await editMarkup(c.chatId, c.msg.message_id, notifySettingsKeyboard(next)) } catch { /* noop */ }
    await c.answer(next ? 'Напоминания включены 🔔' : 'Напоминания выключены 🔕')
  })
}
