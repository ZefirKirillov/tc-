// trackcheck/keyboards/workouts.py

import { btn, kb, withBack } from '../tg.js'
import { BACK_BUTTON_TEXT, BACK_BUTTON_CALLBACK } from '../config.js'

const backRow = () => [btn(BACK_BUTTON_TEXT, BACK_BUTTON_CALLBACK)]

export const workoutMainReplyKeyboard = () => kb(withBack([
  [btn('🏋️ Добавить выполнение', 'menu_workout_add'), btn('🤳 Оценка тела', 'menu_photo_analysis')],
  [btn('📋 Управление', 'menu_workout_manage'), btn('📊 История', 'workout_history')],
]))

export function workoutManageReplyKeyboard(mode = 'ai') {
  const rows = [[btn('🆕 Новый план (ИИ)', 'wp_new_plan'), btn('📝 Загрузить свой план', 'wp_mode_manual')]]
  if (mode === 'ai') rows.unshift([btn('✏️ Редактировать план (ИИ)', 'wp_edit_plan')])
  return kb(withBack(rows))
}

export const workoutMainKeyboard = workoutMainReplyKeyboard

/** items: [[id, name]] laid out two per row */
function pairs(items, cb) {
  const rows = []
  let row = []
  items.forEach(([id, name], i) => {
    row.push(btn(name, cb(id)))
    if (row.length === 2 || i === items.length - 1) { rows.push(row); row = [] }
  })
  return rows
}

export function workoutCategoriesKeyboard(categories, action = 'add') {
  const rows = pairs(categories, id => (action === 'add' ? `w_add_cat_${id}` : `w_manage_cat_${id}`))
  if (action === 'manage') rows.push([btn('➕ Создать категорию', 'w_cat_new')])
  return kb(withBack(rows))
}

export const workoutCategoryActionsKeyboard = (catId) => kb(withBack([
  [btn('📋 Упражнения', `w_manage_exercises_${catId}`)],
  [btn('✏️ Переименовать', `w_cat_rename_${catId}`), btn('❌ Удалить', `w_cat_delete_${catId}`)],
]))

export function workoutExercisesKeyboard(exercises, catId, action = 'add') {
  const rows = pairs(exercises, id => (action === 'add' ? `w_add_ex_${id}` : `w_manage_ex_${id}`))
  if (action === 'manage') rows.push([btn('➕ Создать упражнение', `w_ex_new_${catId}`)])
  return kb(withBack(rows))
}

export const workoutExerciseActionsKeyboard = (exId) => kb(withBack([
  [btn('✏️ Переименовать', `w_ex_rename_${exId}`), btn('❌ Удалить', `w_ex_delete_${exId}`)],
  [btn('🎯 Установить цель', `w_ex_set_goal_${exId}`)],
]))

export const workoutContinueKeyboard = () => kb(withBack([
  [btn('✅ Добавить ещё', 'w_continue_yes')],
  [btn('❌ Закончить', 'workout_main')],
]))

export const workoutExerciseGoalKeyboard = () => kb(withBack([
  [btn('🎯 Силовое', 'goal_strength')],
  [btn('🚴 Кардио', 'goal_cardio')],
]))

export const workoutActionChoiceKeyboard = (exId) => kb(withBack([
  [btn('📝 Ввести вручную', `w_manual_${exId}`)],
  [btn('🎯 Цель достигнута', `w_achieve_goal_${exId}`)],
]))

export const wpModeKeyboard = () => kb(withBack([
  [btn('Создать план с ИИ', 'wp_mode_ai')],
  [btn('📝 Ввести свой план', 'wp_mode_manual')],
]))

export const wpGoalKeyboard = () => kb(withBack([
  [btn('💪 Набор массы', 'wp_goal_mass')],
  [btn('🔥 Похудение', 'wp_goal_loss')],
  [btn('⚡ Сила', 'wp_goal_strength')],
  [btn('🎯 Общая форма', 'wp_goal_fitness')],
]))

export const wpLevelKeyboard = () => kb(withBack([
  [btn('🌱 Новичок', 'wp_level_beginner')],
  [btn('📈 Средний', 'wp_level_intermediate')],
  [btn('🏆 Продвинутый', 'wp_level_advanced')],
]))

export const wpDaysKeyboard = () => kb(withBack([[2, 3, 4, 5].map(n => btn(String(n), `wp_days_${n}`))]))

export const wpPlanReviewKeyboard = () => kb(withBack([
  [btn('✅ Принять план', 'wp_plan_accept')],
  [btn('✏️ Редактировать', 'wp_plan_edit')],
  [btn('🔄 Сгенерировать заново', 'wp_plan_regenerate')],
]))

export const wpPlanReviewKeyboardManual = () => kb(withBack([
  [btn('✅ Принять план', 'wp_plan_accept')],
  [btn('✏️ Редактировать', 'wp_plan_edit')],
  [btn('🔄 Ввести заново', 'wp_mode_manual')],
]))

export const wpEditKeyboard = () => kb([backRow()])

export const wsTodayKeyboard = (extra = false) => kb(withBack([
  [btn('ПОГНАЛИ 💪', 'ws_start')],
  [extra ? btn('Отменить', 'ws_extra_cancel') : btn('Пропустил день', 'ws_skip_day')],
]))

export function wsExerciseKeyboard(isFirst = true) {
  const rows = [
    [btn('✅ Цель выполнена', 'ws_ex_done')],
    [btn('🔄 Заменить', 'ws_ex_replace'), btn('⏭ Пропустить', 'ws_ex_skip')],
  ]
  if (!isFirst) rows.push([btn('↩️ Предыдущее упражнение', 'ws_ex_prev')])
  return kb(withBack(rows))
}

export const wsSkipDayKeyboard = () => kb([backRow()])
export const wsRestDayKeyboard = () => kb([backRow()])

export const wsRestDayActionsKeyboard = () => kb(withBack([
  [btn('✍️ Записать тренировку', 'ws_free_log')],
  [btn('📋 Сделать день из плана', 'ws_pick_day')],
]))

/** days: [[dayKey, label]] */
export const wsPickDayKeyboard = (days) => kb(withBack([
  ...days.map(([key, label]) => [btn(label, `ws_day_${key}`)]),
  [btn('↩️ Назад', 'ws_rest_back')],
]))

export const wsFreeLogKeyboard = () => kb(withBack([[btn('↩️ Назад', 'ws_rest_back')]]))

/** suggestions: [[subId, label]] */
export const wsReplaceKeyboard = (suggestions) => kb(withBack([
  ...suggestions.map(([id, label]) => [btn(label, `ws_sub_${id}`)]),
  [btn('↩️ К упражнению', 'ws_sub_back')],
]))

export const wsRaiseWeightKeyboard = () => kb(withBack([
  [btn('+1.25', 'ws_raise_1.25'), btn('+2.5', 'ws_raise_2.5'), btn('+5', 'ws_raise_5')],
  [btn('Своё значение', 'ws_raise_custom'), btn('Оставить', 'ws_raise_keep')],
]))

export const wpSettingsKeyboard = () => kb(withBack([
  [btn('🔄 Обновить план', 'wp_reset')],
  [btn('📋 Пересмотр упражнений', 'wp_monthly_review')],
]))

export const wpMonthlyReviewKeyboard = (changes) => kb(withBack([
  ...changes.map((ch, i) => [btn(`${i + 1}. ${ch.old_exercise} → ${ch.new_exercise}`, 'wp_review_noop')]),
  [btn('✅ Принять выбранные', 'wp_review_accept')],
  [btn('❌ Отклонить всё', 'wp_review_decline')],
]))

export const workoutAiMainKeyboard = () => kb(withBack([[btn('📋 Настройки плана', 'wp_settings')]]))
