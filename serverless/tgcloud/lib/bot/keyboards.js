// trackcheck/keyboards/{common,dashboard,categories,ai,food,tasks,stats}.py

import { btn, appBtn, kb, withBack, backKeyboard } from '../tg.js'
import { RUSSIAN_TIMEZONES, MINIAPP_URL, BACK_BUTTON_TEXT, BACK_BUTTON_CALLBACK } from '../config.js'
import { daysLeftStr, pyInt, plen, pslice } from '../util.js'

export { backKeyboard }

const backRow = () => [btn(BACK_BUTTON_TEXT, BACK_BUTTON_CALLBACK)]

// ---- common ----

export const timezonePickerKeyboard = (context = 'onboarding') =>
  kb(withBack(RUSSIAN_TIMEZONES.map(([label, tz]) => [btn(label, `tz:${tz}:${context}`)])))

export const retryAiKeyboard = (action) => kb(withBack([[btn('🔄 Попробовать еще раз', `retry_ai:${action}`)]]))

// ---- dashboard ----

export const openAppButton = (text = '🚀 Открыть приложение') => appBtn(text, MINIAPP_URL)

/** Root screen: no «Назад» here. */
export const mainMenuKeyboard = () => kb([
  [openAppButton('🚀 Открыть TrackCheck')],
  [btn('📒 Рефлексия', 'menu_reflection'), btn('⭐ Ранг', 'menu_rank')],
  [btn('🏋️ Тренировки', 'menu_workouts'), btn('Check', 'menu_ai')],
  [btn('🍽 Диета', 'menu_diet'), btn('📝 Задачи', 'menu_tasks')],
])

export function urgentTasksKeyboard(tasks, today) {
  if (!tasks.length) return null
  return kb(tasks.map(t => {
    let label = (t.is_priority ? '🔥 ' : '⏰ ') + t.title
    if (plen(label) > 32) label = pslice(label, 0, 29) + '...'
    if (t.days_left !== null && t.days_left !== undefined) label += ` – ${daysLeftStr(t.deadline, today)}`
    return [btn(label, `task_done_${t.id}`)]
  }))
}

// ---- categories ----

export const reflectionKeyboard = () => kb(withBack([
  [btn('😴 Сон', 'refl:сон'), btn('🎮 Зависание', 'refl:зависание')],
  [btn('🎯 Настрой', 'refl:настрой')],
]))

export const ratingKeyboard = () => kb(withBack([
  [1, 2, 3, 4, 5].map(i => btn(String(i), `rate:${i}`)),
  [6, 7, 8, 9, 10].map(i => btn(String(i), `rate:${i}`)),
]))

export const lowRatingKeyboard = (category) => kb(withBack([
  [btn('Разобрать с ИИ', `analyze_low:${category}`)],
  [btn('🔙 Пропустить', 'skip_analysis')],
]))

// ---- ai ----

export const photoAnalysisCancelKeyboard = () => kb(withBack([[btn('❌ Отмена', 'photo_analysis_cancel')]]))
export const photoAnalysisBackKeyboard = () => kb([backRow()])
export const aiReplyKeyboard = () => kb(withBack([[btn('💡 Дай мне совет', 'ai_advice')]]))

// ---- food ----

export const dietMenuReplyKeyboard = () => kb(withBack([
  [btn('🍎 Записать еду', 'diet_food'), btn('⚖️ Записать вес', 'diet_weight')],
  [btn('🧮 Рассчитать % жира', 'diet_bodyfat'), btn('📖 История еды', 'diet_food_history')],
  [btn('📈 Графики веса и % жира', 'diet_charts'), btn('⚙️ Изменить цель', 'diet_goal')],
]))

export const mealTypeKeyboard = () => kb(withBack([
  [btn('🍳 Завтрак', 'meal_type:Завтрак'), btn('🥗 Обед', 'meal_type:Обед')],
  [btn('🍽 Ужин', 'meal_type:Ужин'), btn('🍪 Перекус', 'meal_type:Перекус')],
  [btn('🔙 Отмена', 'meal_entry_cancel')],
]))

export const mealChosenKeyboard = () => kb(withBack([
  [btn('✏️ Записать калории вручную', 'meal_entry_manual')],
  [btn('❌ Отмена', 'meal_entry_cancel')],
]))

export const saveFoodKeyboard = () => kb(withBack([
  [btn('💾 Сохранить в «Мои блюда»', 'save_food_yes')],
  [btn('➡️ Пропустить', 'save_food_skip')],
]))

export const myFoodsKeyboard = (foods) => kb(withBack([
  ...foods.map(f => [btn(`${f.name} (${pyInt(f.calories)} ккал)`, `food_choose_${f.name}`)]),
  [btn('➕ Создать новое блюдо', 'food_create_new')],
  [btn('🔙 Отмена', 'food_cancel')],
]))

export const genderKeyboard = () => kb(withBack([
  [btn('🚹 Мужской', 'gender_male'), btn('🚺 Женский', 'gender_female')],
]))

export const activityKeyboard = () => kb(withBack([
  [btn('1️⃣ Сидячий (нет тренировок)', 'activity_1.2')],
  [btn('2️⃣ Лёгкий (1-3 раза/нед)', 'activity_1.375')],
  [btn('3️⃣ Умеренный (3-5 раз/нед)', 'activity_1.55')],
  [btn('4️⃣ Высокий (6-7 раз/нед)', 'activity_1.725')],
  [btn('5️⃣ Очень высокий (физ. работа + спорт)', 'activity_1.9')],
]))

export const goalKeyboard = () => kb(withBack([
  [btn('🔻 Снизить вес', 'goal_loss')],
  [btn('🔹 Поддерживать вес', 'goal_maintain')],
  [btn('🔺 Набрать вес', 'goal_gain')],
]))

export const dietConfirmKeyboard = () => kb(withBack([
  [btn('✅ Подтвердить', 'diet_confirm')],
  [btn('🔄 Заново', 'diet_restart')],
]))

export const dietConfirmFoodKeyboard = () => kb(withBack([
  [btn('✅ Да, верно', 'food_confirm_yes')],
  [btn('🔄 Ввести заново', 'food_confirm_redo')],
  [btn('✏️ Ввести калории вручную', 'food_confirm_manual')],
  [btn('❌ Отмена', 'food_cancel')],
]))

export const foodAddMoreKeyboard = () => kb(withBack([
  [btn('✅ Да, добавить ещё', 'food_add_more_yes')],
  [btn('❌ Нет, в меню', 'back_to_main')],
]))

export const foodCancelKeyboard = () => kb(withBack([[btn('❌ Отмена', 'food_cancel')]]))

// ---- tasks ----

export function tasksMenuKeyboard(tasks, today) {
  const rows = tasks.map(t => {
    const prefix = t.is_priority ? '🔥 ' : ''
    let title = t.title
    if (plen(title) > 28) title = pslice(title, 0, 25) + '...'
    let suffix = ''
    if (t.deadline) suffix = ` ⏰${daysLeftStr(t.deadline, today)}`
    if (t.repeat_days) suffix += ' 🔁'
    const label = `${t.is_done ? '✅ ' : ''}${prefix}${title}${suffix}`
    return [btn(label, t.is_done ? 'task_noop' : `task_done_${t.id}`), btn('🗑', `task_del_${t.id}`)]
  })
  rows.push([btn('➕ Новая задача', 'task_new')])
  return kb(withBack(rows))
}

export const tasksConfirmKeyboard = (taskId) => kb(withBack([
  [btn('✅ Да, выполнена', `task_confirm_${taskId}`), btn('❌ Нет', 'back_to_main')],
]))

export const taskRepeatKeyboard = () => kb(withBack([
  [btn('1️⃣ Разовая', 'task_type_once')],
  [btn('🔁 Повторяющаяся', 'task_type_repeat')],
]))

export function taskDaysKeyboard(selected) {
  const days = [[0, 'Пн'], [1, 'Вт'], [2, 'Ср'], [3, 'Чт'], [4, 'Пт'], [5, 'Сб'], [6, 'Вс']]
  return kb(withBack([
    days.map(([n, name]) => btn(`${selected.includes(String(n)) ? '✅' : ''}${name}`, `task_day_${n}`)),
    [btn('✔️ Готово', 'task_days_done')],
  ]))
}

export const taskPriorityKeyboard = () => kb(withBack([
  [btn('🔥 Да, важная', 'task_priority_yes'), btn('Нет', 'task_priority_no')],
]))

export const taskDeadlineKeyboard = () => kb(withBack([
  [btn('📅 Добавить дедлайн', 'task_deadline_yes'), btn('Пропустить', 'task_deadline_no')],
]))

// ---- stats ----

export const statsKeyboard = () => kb(withBack([
  [btn('📆 Неделя', 'stats:week'), btn('🗓 Месяц', 'stats:month')],
  [btn('📈 График неделя', 'stats:chart_week'), btn('📈 График месяц', 'stats:chart_month')],
]))

export const rankBackKeyboard = () => kb([backRow()])

// ---- notify ----

export const notifySettingsKeyboard = (enabled) => kb([
  [btn(enabled ? '🔔 Напоминания: ВКЛ' : '🔕 Напоминания: ВЫКЛ', 'notify_toggle')],
])
