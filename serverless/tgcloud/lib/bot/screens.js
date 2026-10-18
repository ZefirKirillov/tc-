// trackcheck/screens.py + handlers/navigation.py — the universal «🔙 Назад».

import * as repo from '../repo.js'
import { onCallback, onMessage } from '../router.js'
import { send, del, btn, kb, withBack } from '../tg.js'
import { BACK_BUTTON_TEXT } from '../config.js'
import { formatFullPlan } from '../workout_service.js'
import { AIAdvisorState, AIPlanState } from './states.js'
import { backKeyboard, aiReplyKeyboard } from './keyboards.js'
import * as K from './workout_keyboards.js'
import { sendMainMenu } from './dashboard.js'
import { showReflectionMenu } from './categories.js'
import {
  showWorkoutMainMenu, showAiWorkoutToday, showWorkoutManageMenu, doWorkoutManage,
  showWorkoutHistoryPage, showHistoryPage, planDayButtons, planDayExercises, notesKeyboard, NOTES_TEXT,
} from './workouts.js'
import { showDietMenu, dietLogFoodStart, showFoodHistoryPage } from './food.js'
import { showTasksMenu } from './tasks.js'
import { showStatsChoice, showRank } from './stats.js'

const MAIN_MENU_CALLBACKS = new Set(['menu_reflection', 'menu_rank', 'menu_workouts', 'menu_ai', 'menu_diet', 'menu_tasks'])

function isMainMenuKeyboard(markup) {
  const cbs = (markup.inline_keyboard || []).flat().map(b => b.callback_data).filter(Boolean)
  return cbs.length > 0 && cbs.every(x => MAIN_MENU_CALLBACKS.has(x))
}

async function screenSend(c, text, markup, tempsKey) {
  await del(c.chatId, c.s.temps[tempsKey])
  if (!markup) markup = backKeyboard()
  else if (markup.inline_keyboard && !isMainMenuKeyboard(markup)) markup = kb(withBack(markup.inline_keyboard))
  const msg = await send(c.chatId, text, { reply_markup: markup })
  c.s.temps[tempsKey] = msg.message_id
}

const SCREENS = {
  main: (c) => sendMainMenu(c),
  reflection: (c) => showReflectionMenu(c),
  workout: (c) => showWorkoutMainMenu(c),
  workout_today: (c) => showAiWorkoutToday(c),
  workout_manage: (c) => showWorkoutManageMenu(c),
  categories: (c) => doWorkoutManage(c),
  diet: async (c) => ((await repo.getDietProfile(c.userId)) ? showDietMenu(c) : sendMainMenu(c)),
  diet_meal: (c) => dietLogFoodStart(c),
  tasks: (c) => showTasksMenu(c),
  stats: (c) => showStatsChoice(c),
  rank: (c) => showRank(c),
  ai: async (c) => {
    c.s.setState(AIAdvisorState.waiting_for_question)
    await screenSend(c, 'Check тут, чем помочь?', aiReplyKeyboard(), 'ai_advisor')
    c.s.navPush('ai')
  },
  history: async (c) => { c.s.historyPage = 0; await showHistoryPage(c) },
  workout_history: (c) => showWorkoutHistoryPage(c, 0),
  food_history: async (c) => { c.s.foodHistoryPage = 0; await showFoodHistoryPage(c) },
  wp_mode: async (c) => {
    c.s.setState(AIPlanState.choosing_mode)
    const name = await repo.getUserName(c.userId)
    await screenSend(c, `${name}, давай настроим тренировки!\n\nСоздать план с ИИ или введёшь свой?`, K.wpModeKeyboard(), 'workout_menu')
    c.s.navPush('wp_mode')
  },
  wp_goal: async (c) => {
    c.s.setState(AIPlanState.choosing_goal)
    await screenSend(c, 'Создание плана тренировок\n\nШаг 1 из 3\nКакая твоя цель?', K.wpGoalKeyboard(), 'workout_menu')
    c.s.navPush('wp_goal')
  },
  wp_level: async (c) => {
    c.s.setState(AIPlanState.choosing_level)
    await screenSend(c, 'Создание плана тренировок\n\nШаг 2 из 3\nТвой уровень подготовки?', K.wpLevelKeyboard(), 'workout_menu')
    c.s.navPush('wp_level')
  },
  wp_days: async (c) => {
    c.s.setState(AIPlanState.choosing_days_count)
    await screenSend(c, 'Создание плана тренировок\n\nШаг 3 из 3\nСколько тренировок в неделю готов делать?', K.wpDaysKeyboard(), 'workout_menu')
    c.s.navPush('wp_days')
  },
  wp_notes: async (c) => {
    c.s.setState(AIPlanState.entering_extra_notes)
    await screenSend(c, NOTES_TEXT, notesKeyboard(), 'workout_menu')
    c.s.navPush('wp_notes')
  },
  wp_review: async (c) => {
    const data = c.s.getData()
    let plan = data.wp_plan
    if (!plan) {
      const pd = await repo.getAiPlan(c.userId)
      plan = pd ? pd.plan : null
    }
    if (!plan) return SCREENS.workout_today(c)
    c.s.setState(AIPlanState.reviewing_plan)
    const markup = data.wp_mode === 'manual' ? K.wpPlanReviewKeyboardManual() : K.wpPlanReviewKeyboard()
    await screenSend(c, formatFullPlan(plan, data.wp_goal || '', data.wp_level || '', data.wp_days ?? 3), markup, 'workout_menu')
    c.s.navPush('wp_review')
  },
  wp_edit: async (c) => {
    c.s.setState(AIPlanState.editing_plan)
    await screenSend(c, 'Что изменить в плане?\n\nНапример:\n«убери приседания, замени на жим ногами»\n«добавь кардио в пятницу»', null, 'workout_menu')
    c.s.navPush('wp_edit')
  },
  wp_manual: async (c) => {
    c.s.setState(AIPlanState.entering_manual_plan)
    await screenSend(c, 'Отправь план одним сообщением в формате:\nДень недели:\nНазвание упражнения - СетыxПовторения(Вес)\n\n'
      + 'Пример: Жим лёжа - 3x5(110кг)', null, 'workout_menu')
    c.s.navPush('wp_manual')
  },
  wp_review_decline_prompt: (c) => showAiWorkoutToday(c),
  wex_days: async (c) => {
    const pd = await repo.getAiPlan(c.userId)
    if (!pd) return SCREENS.workout_today(c)
    c.s.setState(AIPlanState.editing_plan)
    c.s.updateData({ wp_edit_mode: 'exercise' })
    await screenSend(c, 'Выбери день тренировки:', kb(planDayButtons(pd)), 'workout_menu')
    c.s.navPush('wex_days')
  },
  wex_ex: async (c) => {
    const dayKey = c.s.getData().wp_edit_day
    const pd = dayKey ? await repo.getAiPlan(c.userId) : null
    const exercises = pd ? planDayExercises(pd, dayKey) : []
    if (!exercises.length) return SCREENS.wex_days(c)
    const buttons = exercises.map((ex, i) => [btn(String(ex.exercise ?? ex.name ?? `Упражнение ${i + 1}`), `wex_ex_${i}`)])
    await screenSend(c, 'Выбери упражнение для замены:', kb(buttons), 'workout_menu')
    c.s.navPush('wex_ex')
  },
  wex_replace: async (c) => {
    const name = c.s.getData().wp_edit_ex_name
    if (!name) return SCREENS.wex_ex(c)
    await screenSend(c, `Чем заменить «${name}»?\n\nНапиши название нового упражнения:`, null, 'workout_menu')
    c.s.navPush('wex_replace')
  },
}

export async function renderScreen(c, screen) {
  await (SCREENS[screen] || SCREENS.main)(c)
}

// Wizard steps keep their data in the FSM — «Назад» must not wipe it there.
const KEEP_STATE = new Set(['wp_mode', 'wp_goal', 'wp_level', 'wp_days', 'wp_notes', 'wp_review',
  'wp_edit', 'wp_manual', 'wex_days', 'wex_ex', 'wex_replace', 'diet_meal', 'ai'])

async function goBack(c) {
  const screen = c.s.navPop()
  if (!KEEP_STATE.has(screen)) c.s.clear()
  await renderScreen(c, screen)
}

export function register() {
  onMessage({ text: BACK_BUTTON_TEXT }, async (c) => { await c.deleteMsg(); await goBack(c) })
  onCallback({ data: 'nav_back' }, goBack)
}
