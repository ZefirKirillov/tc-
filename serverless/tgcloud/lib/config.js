// Constants from trackcheck/config.py.

import { MINIAPP_BASE_URL } from './secrets.js'

export { MINIAPP_BASE_URL }

export function miniappUrl(tab = '') {
  const base = MINIAPP_BASE_URL.replace(/\/+$/, '') + '/'
  return tab ? `${base}?tab=${tab}` : base
}

export const MINIAPP_URL = miniappUrl()

export const BACK_BUTTON_TEXT = '🔙 Назад'
export const BACK_BUTTON_CALLBACK = 'nav_back'

export const RANKS = {
  1: { name: 'Первые Искры', emoji: '✨', sparks_needed: 1, motivation: 'Первый шаг сделан! Искра зажжена, путь начат!' },
  2: { name: 'Искрящийся', emoji: '💥', sparks_needed: 7, motivation: 'Ты искришься энергией! Каждый день делает тебя ярче!' },
  3: { name: 'Горящий Огнем', emoji: '🔥', sparks_needed: 14, motivation: 'Ты горишь огнём прогресса! Ничто не остановит твой настрой!' },
  4: { name: 'Восходящая звезда', emoji: '💫', sparks_needed: 31, motivation: 'Ты восходишь над горизонтом! Твой свет заметен всем!' },
  5: { name: 'Супер звезда', emoji: '⭐️', sparks_needed: 62, motivation: 'Супер звезда во всей красе! Твоя дисциплина вдохновляет!' },
  6: { name: 'Яркий', emoji: '🌟', sparks_needed: 93, motivation: 'Ты сияешь как никто другой! Яркость твоей дисциплины ослепляет!' },
  7: { name: 'Самый Яркий', emoji: '☀️', sparks_needed: 183, motivation: 'Ты — центр вселенной продуктивности! Самый яркий из всех!' },
  8: { name: 'Нейтронная Звезда', emoji: '❤️‍🔥', sparks_needed: 365, motivation: 'Невероятная плотность дисциплины! Ты — явление вселенского масштаба!' },
}

export const MAX_SPARKS_PER_DAY = 2
export const SPARK_FOR_CATEGORIES = 1
export const SPARK_FOR_WORKOUT = 1

export const DEFAULT_TIMEZONE = 'Europe/Moscow'

export const RUSSIAN_TIMEZONES = [
  ['Калининград (UTC+2)', 'Europe/Kaliningrad'],
  ['Москва (UTC+3)', 'Europe/Moscow'],
  ['Самара (UTC+4)', 'Europe/Samara'],
  ['Екатеринбург (UTC+5)', 'Asia/Yekaterinburg'],
  ['Омск (UTC+6)', 'Asia/Omsk'],
  ['Красноярск (UTC+7)', 'Asia/Krasnoyarsk'],
  ['Иркутск (UTC+8)', 'Asia/Irkutsk'],
  ['Владивосток (UTC+10)', 'Asia/Vladivostok'],
]

export const WEEKDAY_NAMES = { 0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт', 4: 'Пт', 5: 'Сб', 6: 'Вс' }
export const WEEKDAY_SHORT = WEEKDAY_NAMES
export const WEEKDAY_RU = { 0: 'Понедельник', 1: 'Вторник', 2: 'Среда', 3: 'Четверг', 4: 'Пятница', 5: 'Суббота', 6: 'Воскресенье' }
export const WEEKDAY_KEY = { 0: 'monday', 1: 'tuesday', 2: 'wednesday', 3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday' }
export const WEEKDAY_FROM_KEY = Object.fromEntries(Object.entries(WEEKDAY_KEY).map(([k, v]) => [v, Number(k)]))
