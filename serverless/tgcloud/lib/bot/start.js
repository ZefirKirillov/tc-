// trackcheck/handlers/start.py — onboarding, /start, /app, /timezone.

import * as repo from '../repo.js'
import { onCallback, onMessage } from '../router.js'
import { send, del, btn, kb, withBack, appBtn } from '../tg.js'
import { getUserTimezone, setUserTimezone } from '../dates.js'
import { one } from '../turso.js'
import { RUSSIAN_TIMEZONES, MINIAPP_URL } from '../config.js'
import { timezonePickerKeyboard, openAppButton } from './keyboards.js'
import { WorkoutSessionState } from './states.js'
import { sendMainMenu } from './dashboard.js'
import { sendTemp } from './helpers.js'
import { wsStartWorkout } from './workouts.js'

const WELCOME_TEXT = '👋 <b>Привет! Я TrackCheck</b> — помогаю держать форму и не терять дисциплину.\n'
  + '\n'
  + 'Что внутри:\n'
  + '🏋️ <b>Тренировки</b> — план от ИИ или свой, отмечаешь упражнения прямо в зале\n'
  + '📒 <b>Чек-ин дня</b> — сон, зависание и настрой за минуту; еду и активность я оценю сам\n'
  + '🍽 <b>Питание</b> — норма калорий, еда текстом или по фото, вес и % жира\n'
  + '📝 <b>Задачи</b> — с приоритетом, дедлайнами и повтором\n'
  + '💬 <b>Check</b> — советы по твоим данным\n'
  + '🔥 <b>Серия, искры и ранги</b> — за каждый закрытый день\n'
  + '\n'
  + 'Всё это удобнее всего в <b>приложении TrackCheck</b> прямо в Telegram.\n'
  + '\n'
  + 'Сначала выбери часовой пояс — жми «ПОГНАЛИ» 👇'

const READY_TEXT = '✅ <b>Готово!</b> Теперь открой приложение — там весь твой день:\n'
  + '\n'
  + '• кнопка <b>«TrackCheck»</b> слева от поля ввода\n'
  + '• или кнопка ниже\n'
  + '• или команда /app\n'
  + '\n'
  + 'Здесь, в чате, я буду напоминать о тренировках, задачах и серии 🔥'

export async function sendReadyMessage(chatId) {
  await send(chatId, READY_TEXT, { parse_mode: 'HTML', reply_markup: kb([[openAppButton('🚀 Открыть TrackCheck')]]) })
}

async function cmdStart(c) {
  await c.deleteMsg()
  const { userId, chatId, s } = c
  if (!(await repo.userExists(userId))) {
    const msg = await send(chatId, WELCOME_TEXT, { parse_mode: 'HTML', reply_markup: kb(withBack([[btn('ПОГНАЛИ 💪', 'ws_start')]])) })
    // The Python bot deleted this after 10 minutes; here it stays until «ПОГНАЛИ».
    s.welcomeMsg = msg.message_id
    return
  }
  await repo.saveUserSettings(userId, c.from.username, c.from.first_name)
  await repo.updateStreak(userId)
  await sendMainMenu(c)
}

async function handleStartButton(c) {
  // One «ПОГНАЛИ» button: onboarding, and starting the session from today's plan.
  if (c.s.getState() === WorkoutSessionState.viewing_plan) await wsStartWorkout(c)
  else await startOnboarding(c)
}

async function startOnboarding(c) {
  const { userId, chatId, s } = c
  s.clear()
  await c.deleteMsg()
  s.welcomeMsg = null
  await repo.saveUserSettings(userId, c.from.username, c.from.first_name)
  await repo.updateStreak(userId)
  const row = await one('SELECT timezone FROM user_settings WHERE user_id = ?', [userId])
  if (!row || !row.timezone) {
    const msg = await send(chatId,
      '🕒 Для начала выбери свой часовой пояс — так все даты, стрики и напоминания '
      + 'будут работать по твоему времени, а не по серверному.\n\n'
      + 'Позже его можно поменять командой /timezone.',
      { reply_markup: timezonePickerKeyboard('onboarding') })
    s.temps.timezone_picker = msg.message_id
    return
  }
  await sendReadyMessage(chatId)
  await sendMainMenu(c)
}

async function handleTimezoneChoice(c) {
  const parts = c.data.split(':')
  if (parts.length !== 3) {
    await c.answer('❌ Ошибка выбора часового пояса', true)
    return
  }
  const [, tz, context] = parts
  if (!RUSSIAN_TIMEZONES.some(([, t]) => t === tz)) {
    await c.answer('❌ Неизвестный часовой пояс', true)
    return
  }
  await setUserTimezone(c.userId, tz)
  await del(c.chatId, c.s.temps.timezone_picker)
  delete c.s.temps.timezone_picker
  const label = (RUSSIAN_TIMEZONES.find(([, t]) => t === tz) || [tz])[0]
  await c.answer(`Часовой пояс: ${label} ✅`)
  if (context === 'onboarding') {
    await sendReadyMessage(c.chatId)
    await sendMainMenu(c)
  } else {
    await sendTemp(c, `🕒 Часовой пояс изменён на: ${label}`)
  }
}

async function cmdApp(c) {
  await c.deleteMsg()
  const msg = await c.reply(
    '🚀 <b>TrackCheck</b> — тренировки, чек-ин, питание и задачи в одном окне.\n\n'
    + 'Совет: приложение всегда под рукой — кнопка <b>«TrackCheck»</b> слева от поля ввода.',
    { reply_markup: kb([[appBtn('🚀 Открыть TrackCheck', MINIAPP_URL)]]), parse_mode: 'HTML' })
  c.s.temps.app_link = msg.message_id
}

async function cmdTimezone(c) {
  await c.deleteMsg()
  const current = await getUserTimezone(c.userId)
  const label = (RUSSIAN_TIMEZONES.find(([, t]) => t === current) || [current])[0]
  const msg = await c.reply(`🕒 Текущий часовой пояс: ${label}\n\nВыбери новый:`,
    { reply_markup: timezonePickerKeyboard('change') })
  c.s.temps.timezone_picker = msg.message_id
}

export function register() {
  onMessage({ command: 'start' }, cmdStart)
  onCallback({ data: 'ws_start' }, handleStartButton)
  onCallback({ prefix: 'tz:' }, handleTimezoneChoice)
  onMessage({ command: 'app' }, cmdApp)
  onMessage({ command: 'timezone' }, cmdTimezone)
}
