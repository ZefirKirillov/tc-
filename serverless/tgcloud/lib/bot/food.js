// trackcheck/handlers/food.py — diet profile, food log, weight, body fat.

import * as repo from '../repo.js'
import { onCallback, onMessage } from '../router.js'
import { send, del, edit, editMarkup, typing, btn, kb, withBack, sendPhoto, api } from '../tg.js'
import { all, one } from '../turso.js'
import { ddmmyyyy } from '../dates.js'
import {
  MACRO_KEYS, createNewProgressBar, foodConfirmText, formatMacros, nutritionMacros, pyInt, pyRound,
  pyIntParse, pyFloatParse, pyFloat,
} from '../util.js'
import * as ai from '../ai.js'
import { syncDietRatingForToday } from '../tracker.js'
import { renderChart } from '../charts.js'
import { DietState } from './states.js'
import {
  backKeyboard, retryAiKeyboard, dietMenuReplyKeyboard, mealTypeKeyboard, mealChosenKeyboard, saveFoodKeyboard,
  genderKeyboard, activityKeyboard, goalKeyboard, dietConfirmKeyboard, dietConfirmFoodKeyboard,
  foodAddMoreKeyboard, foodCancelKeyboard,
} from './keyboards.js'
import { deleteTempMessages, sendTemp } from './helpers.js'
import { downloadPhoto } from './ai.js'

const tryEdit = async (chatId, msgId, text, opts) => { try { await edit(chatId, msgId, text, opts); return true } catch { return false } }

function loggedText(calories, macros) {
  let text = `✅ Записано: ${pyInt(calories)} ккал`
  if (macros) text += ` (${formatMacros(macros.protein, macros.fat, macros.carbs)})`
  return text
}

/** «350» or «350 20 10 40» → [kcal, macros|null]; throws on bad input. */
function parseManualNutrition(text) {
  const parts = (text || '').replace(/,/g, '.').split(/\s+/).filter(Boolean)
  if (parts.length !== 1 && parts.length !== 4) throw new Error('bad')
  const values = parts.map(pyFloatParse)
  if (!values.every(Number.isFinite)) throw new Error('bad')
  const calories = values[0]
  if (calories <= 0 || calories > 10000) throw new Error('bad')
  if (values.length === 1) return [calories, null]
  if (values.slice(1).some(v => v < 0 || v > 1000)) throw new Error('bad')
  return [calories, { protein: values[1], fat: values[2], carbs: values[3] }]
}

const MANUAL_NUTRITION_HINT = 'Можно сразу с БЖУ через пробел: ккал белки жиры углеводы, например 350 20 10 40.'

/** sync_diet_rating_for_today, without failing the handler. */
async function syncDiet(userId) {
  try { await syncDietRatingForToday(userId) } catch (e) { console.error('[DIET RATING]', e) }
}

async function dropLastMenu(c) {
  if (c.s.lastMenu) {
    await del(c.chatId, c.s.lastMenu)
    c.s.lastMenu = null
  }
}

async function handleDiet(c) {
  await c.deleteMsg()
  c.s.clear()
  const profile = await repo.getDietProfile(c.userId)
  await dropLastMenu(c)
  await deleteTempMessages(c, true)
  if (!profile) {
    c.s.setState(DietState.weight)
    const msg = await c.reply('📝 Введи свой вес (в кг):', { reply_markup: backKeyboard() })
    c.s.temps.diet_setup = msg.message_id
    return
  }
  await showDietMenu(c)
}

export async function showDietMenu(c) {
  const { s, userId, chatId } = c
  const profile = await repo.getDietProfile(userId)
  if (!profile) return
  const todayCal = await repo.getTodayCalories(userId)
  const goal = profile.daily_calories
  const percent = goal > 0 ? todayCal / goal * 100 : 0
  const bar = createNewProgressBar(Math.trunc(Math.floor(percent / 10)), 10)
  const macros = await repo.getTodayMacros(userId)
  const goals = await repo.getMacroGoals(userId, profile)
  const macroLine = MACRO_KEYS.map((k, i) => `${['Б', 'Ж', 'У'][i]} ${pyRound(macros[k])}/${pyRound(goals[k])}`).join(' · ') + ' г'
  const log = await repo.getTodayFoodLog(userId)
  const foodSummary = log.length
    ? log.map(r => {
      const m = formatMacros(r.protein, r.fat, r.carbs)
      return `${r.meal_type}: ${r.food_description} (${pyInt(r.calories)} ккал${m ? ', ' + m : ''})`
    }).join('\n')
    : 'Пока нет записей.'
  const text = `🍽 Меню диеты

Цель: ${pyInt(goal)} ккал/день
Съедено сегодня: ${pyInt(todayCal)} ккал (${pyInt(percent)}%)
${bar} ${pyInt(percent)}%
БЖУ: ${macroLine}

Сегодня:
${foodSummary}

Выбери действие:`
  const msg = await send(chatId, text, { reply_markup: dietMenuReplyKeyboard() })
  s.navPush('diet')
  s.temps.diet_menu = msg.message_id
}

export async function dietLogFoodStart(c) {
  const { s, chatId } = c
  await del(chatId, s.temps.diet_menu)
  await dropLastMenu(c)
  await deleteTempMessages(c, true)
  s.clear()
  s.setState(DietState.meal_type)
  const msg = await send(chatId, 'Выбери приём пищи:', { reply_markup: mealTypeKeyboard() })
  s.temps.diet_temp = msg.message_id
  s.navPush('diet_meal')
}

async function dietChooseMeal(c) {
  const meal = c.data.split(':').slice(1).join(':')
  if (!['Завтрак', 'Обед', 'Ужин', 'Перекус'].includes(meal)) return
  c.s.updateData({ meal_type: meal })
  await del(c.chatId, c.s.temps.diet_temp)
  const msg = await c.reply(`Приём пищи: <b>${meal}</b>\n\nОпиши что съел — ИИ посчитает калории и БЖУ, или запиши вручную:`,
    { parse_mode: 'HTML', reply_markup: mealChosenKeyboard() })
  c.s.temps.diet_temp = msg.message_id
}

async function mealEntryManual(c) {
  await del(c.chatId, c.s.temps.diet_temp)
  c.s.updateData({ food_description: '' })
  c.s.setState(DietState.manual_calories)
  const msg = await c.reply(`✏️ Введи количество калорий (число).\n${MANUAL_NUTRITION_HINT}`, { reply_markup: foodCancelKeyboard() })
  c.s.temps.diet_temp = msg.message_id
}

async function mealEntryCancel(c) {
  await del(c.chatId, c.s.temps.diet_temp)
  c.s.clear()
  await showDietMenu(c)
}

async function mealTypeTextForward(c) {
  c.s.setState(DietState.food_description)
  await processFoodDescription(c)
}

async function mealTypePhotoForward(c) {
  c.s.setState(DietState.food_description)
  await processFoodPhoto(c)
}

async function dietChooseMyFood(c) {
  const name = c.data.split('_').slice(2).join('_')
  const row = await one('SELECT calories, protein, fat, carbs FROM my_foods WHERE user_id = ? AND name = ?', [c.userId, name])
  if (row) {
    const macros = row.protein === null ? null : { protein: row.protein, fat: row.fat, carbs: row.carbs }
    c.s.updateData({ food_description: name, food_calories: row.calories, food_macros: macros })
    await c.deleteMsg()
    c.s.setState(DietState.food_confirm)
    await c.reply(foodConfirmText(name, row.calories, macros), { reply_markup: dietConfirmFoodKeyboard() })
  } else {
    await c.answer('❌ Блюдо не найдено', true)
    await dietLogFoodStart(c)
  }
}

async function dietCreateNewFood(c) {
  await c.deleteMsg()
  c.s.setState(DietState.food_description)
  const msg = await c.reply('🍽 Опиши, что ты съел, или отправь фото блюда:\n\nИли нажми /cancel для отмены.', { reply_markup: foodCancelKeyboard() })
  c.s.temps.diet_temp = msg.message_id
}

async function cancelToDietMenu(c) {
  c.s.clear()
  await c.deleteMsg()
  await showDietMenu(c)
}

async function processFoodPhoto(c) {
  const { s, chatId } = c
  await del(chatId, s.temps.diet_temp)
  const wait = await c.reply('🔍 Анализирую фото блюда...')
  const image = await downloadPhoto(c.photoFileId)
  if (!image) {
    await tryEdit(chatId, wait.message_id, '❌ Не удалось загрузить фото.')
    return
  }
  s.updateData({ retry_food_photo_file_id: c.photoFileId, retry_action: 'food_photo' })
  const text = await ai.analyzeFoodPhoto(image, ai.FOOD_PHOTO_PROMPT, { userId: c.userId })
  if (text === null) {
    const why = ai.friendlyAiError()
    await tryEdit(chatId, wait.message_id, (why.startsWith('⏳') ? why : '❌ Ошибка анализа фото.') + '\n\n🔄 Нажми кнопку чтобы попробовать ещё раз.',
      { reply_markup: retryAiKeyboard('food_photo') })
    return
  }
  const [description, nutrition] = ai.parseFoodPhoto(text)
  await del(chatId, wait.message_id)
  if (!nutrition) {
    s.updateData({ food_description: description })
    s.setState(DietState.manual_calories)
    const msg = await c.reply(`🍽 Определено: ${description}\n❌ Не удалось оценить калории. Введи вручную (число).\n${MANUAL_NUTRITION_HINT}`,
      { reply_markup: foodCancelKeyboard() })
    s.temps.diet_temp = msg.message_id
    return
  }
  const macros = nutritionMacros(nutrition)
  s.updateData({ food_description: description, food_calories: nutrition.calories, food_macros: macros })
  s.setState(DietState.food_confirm)
  await c.reply(foodConfirmText(description, nutrition.calories, macros, true), { reply_markup: dietConfirmFoodKeyboard() })
}

async function processFoodDescription(c) {
  const { s, chatId } = c
  const description = (c.text || '').trim()
  if (description.length < 3) {
    if (s.temps.diet_error) await del(chatId, s.temps.diet_error)
    const m = await c.reply('❌ Слишком короткое описание. Попробуй ещё раз.')
    s.temps.diet_error = m.message_id
    return
  }
  await del(chatId, s.temps.diet_temp)
  if ('diet_error' in s.temps) {
    await del(chatId, s.temps.diet_error)
    delete s.temps.diet_error
  }
  await typing(chatId)
  s.updateData({ retry_food_description: description, retry_action: 'food_calories' })
  const nutrition = await ai.estimateFoodNutrition(description, { userId: c.userId })
  if (!nutrition) {
    s.updateData({ food_description: description })
    s.setState(DietState.manual_calories)
    const msg = await c.reply('❌ Не удалось определить калории автоматически. Нажми кнопку чтобы попробовать ещё раз.',
      { reply_markup: retryAiKeyboard('food_calories') })
    s.temps.diet_temp = msg.message_id
    return
  }
  const macros = nutritionMacros(nutrition)
  s.updateData({ food_description: description, food_calories: nutrition.calories, food_macros: macros })
  s.setState(DietState.food_confirm)
  await c.reply(foodConfirmText(description, nutrition.calories, macros), { reply_markup: dietConfirmFoodKeyboard() })
}

async function foodConfirmYes(c) {
  try { await editMarkup(c.chatId, c.msg.message_id, null) } catch { /* noop */ }
  const data = c.s.getData()
  const m = data.food_macros || {}
  await repo.saveFoodLog(c.userId, data.meal_type ?? null, data.food_description ?? null, data.food_calories ?? null,
    m.protein ?? null, m.fat ?? null, m.carbs ?? null)
  await syncDiet(c.userId)
  await sendTemp(c, loggedText(data.food_calories, data.food_macros) + '.')
  c.s.setState(DietState.food_confirm)
  await sendTemp(c, 'Хочешь добавить ещё запись?', { reply_markup: foodAddMoreKeyboard() })
}

async function foodAddMore(c) {
  c.s.setState(DietState.meal_type)
  await c.deleteMsg()
  const msg = await c.reply('Выбери приём пищи:', { reply_markup: mealTypeKeyboard() })
  c.s.temps.diet_temp = msg.message_id
}

async function foodConfirmRedo(c) {
  c.s.setState(DietState.meal_type)
  try { await editMarkup(c.chatId, c.msg.message_id, null) } catch { /* noop */ }
  const msg = await send(c.chatId, 'Выбери приём пищи:', { reply_markup: mealTypeKeyboard() })
  c.s.temps.diet_temp = msg.message_id
  await c.deleteMsg()
}

async function foodConfirmManual(c) {
  c.s.setState(DietState.manual_calories)
  try { await editMarkup(c.chatId, c.msg.message_id, null) } catch { /* noop */ }
  const msg = await send(c.chatId, `✏️ Введи количество калорий вручную (число).\n${MANUAL_NUTRITION_HINT}`, { reply_markup: foodCancelKeyboard() })
  c.s.temps.diet_temp = msg.message_id
  await c.deleteMsg()
}

async function manualCalories(c) {
  let calories, macros
  try {
    [calories, macros] = parseManualNutrition(c.text)
  } catch {
    await c.reply('❌ Введи корректное число калорий (например, 350) или ккал и БЖУ (350 20 10 40):')
    return
  }
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.diet_temp)
  const data = c.s.getData()
  await repo.saveFoodLog(c.userId, data.meal_type ?? null, data.food_description ?? '', calories,
    macros ? macros.protein : null, macros ? macros.fat : null, macros ? macros.carbs : null)
  await syncDiet(c.userId)
  c.s.updateData({ manual_calories_value: calories, manual_macros: macros })
  c.s.setState(DietState.new_food_name)
  const msg = await c.reply(`${loggedText(calories, macros)}\n\nСохранить в «Мои блюда»?`, { reply_markup: saveFoodKeyboard() })
  c.s.temps.diet_temp = msg.message_id
}

async function saveFoodSkip(c) {
  const data = c.s.getData()
  await c.deleteMsg()
  c.s.clear()
  await sendTemp(c, loggedText(data.manual_calories_value, data.manual_macros) + '.')
  await showDietMenu(c)
}

async function saveFoodYesPrompt(c) {
  await c.deleteMsg()
  const msg = await c.reply('Введи название блюда для сохранения:', { reply_markup: backKeyboard() })
  c.s.temps.diet_temp = msg.message_id
  c.s.updateData({ awaiting_food_name_input: true })
}

async function saveMyFoodName(c) {
  const name = (c.text || '').trim()
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.diet_temp)
  const data = c.s.getData()
  const m = data.manual_macros || {}
  await repo.addMyFood(c.userId, name, data.manual_calories_value, m.protein ?? null, m.fat ?? null, m.carbs ?? null)
  await sendTemp(c, `✅ Блюдо «${name}» сохранено в Мои блюда.`)
  c.s.clear()
  await sendTemp(c, loggedText(data.manual_calories_value, data.manual_macros) + '.')
  await showDietMenu(c)
}

async function dietLogWeightReply(c) {
  await c.deleteMsg()
  await dropLastMenu(c)
  await deleteTempMessages(c, true)
  c.s.clear()
  c.s.setState(DietState.log_weight)
  const msg = await c.reply('⚖️ Введи свой текущий вес (в кг):', { reply_markup: backKeyboard() })
  c.s.temps.diet_temp = msg.message_id
}

async function dietLogWeightFinish(c) {
  const weight = pyFloatParse((c.text || '').trim().replace(',', '.'))
  if (!Number.isFinite(weight) || weight < 20 || weight > 300) {
    await c.reply('❌ Введи корректный вес (например, 70.5):')
    return
  }
  const { userId } = c
  await del(c.chatId, c.msg.message_id)
  await del(c.chatId, c.s.temps.diet_temp)
  const last = await repo.getLastWeight(userId)
  await repo.saveWeightLog(userId, weight)
  const profile = await repo.getDietProfile(userId)
  let motivation = ''
  if (last) {
    const diff = weight - last
    const a = Math.abs(diff).toFixed(1), d = diff.toFixed(1)
    if (profile && profile.goal_type === 'loss') {
      if (diff < 0) motivation = `\n✅ Отлично! Ты похудел на ${a} кг. Так держать!`
      else if (diff > 0) motivation = `\n⚠️ Вес увеличился на ${d} кг. Не сдавайся, продолжай следить за питанием!`
      else motivation = '\n👌 Вес не изменился. Держим уровень!'
    } else if (profile && profile.goal_type === 'gain') {
      if (diff > 0) motivation = `\n✅ Отлично! Ты набрал ${d} кг. Прогресс!`
      else if (diff < 0) motivation = `\n⚠️ Вес уменьшился на ${a} кг. Поднажми с питанием!`
      else motivation = '\n👌 Вес не изменился.'
    } else if (Math.abs(diff) < 1) motivation = '\n👍 Вес стабилен. Отлично!'
    else if (diff > 0) motivation = `\n📈 Вес вырос на ${d} кг. Если это не входило в планы, обрати внимание.`
    else motivation = `\n📉 Вес снизился на ${a} кг.`
  }
  c.s.clear()
  await sendTemp(c, `✅ Вес ${pyFloat(weight)} кг записан.` + motivation)
  await showDietMenu(c)
}

async function dietBodyFatReply(c) {
  await c.deleteMsg()
  await dropLastMenu(c)
  await deleteTempMessages(c, true)
  c.s.clear()
  c.s.setState(DietState.body_fat_measurements)
  const msg = await c.reply('Введи свои данные в одной строке через пробел:\n'
    + 'рост(см) вес(кг) обхват шеи(см) обхват талии(см) [обхват бёдер(см) для женщин]\n\n'
    + 'Пример для мужчины: 175 70 40 80\n'
    + 'Пример для женщины: 165 60 38 70 95', { reply_markup: backKeyboard() })
  c.s.temps.diet_temp = msg.message_id
}

async function dietBodyFatCalculate(c) {
  const { s, userId, chatId } = c
  const temps = s.temps
  if (temps.body_fat_error) {
    await del(chatId, temps.body_fat_error)
    delete temps.body_fat_error
  }
  const parts = (c.text || '').trim().split(/\s+/).filter(Boolean)
  const fail = async (text) => { const m = await c.reply(text); temps.body_fat_error = m.message_id }
  if (parts.length !== 4 && parts.length !== 5) return fail('❌ Неверное количество чисел. Должно быть 4 (мужчины) или 5 (женщины).')
  const n = parts.map(p => pyFloatParse(p.replace(',', '.')))
  if (!n.every(x => Number.isFinite(x) && x > 0)) return fail('❌ Неверный формат чисел. Используй точки или запятые.')
  temps.body_fat_measurements = c.msg.message_id
  const [height, weight, neck, waist] = n
  const hip = n.length === 5 ? n[4] : null
  let bodyFat
  if (hip !== null) {
    const diff = waist + hip - neck
    if (diff <= 0) return fail('❌ Сумма обхватов талии и бёдер должна быть больше обхвата шеи.')
    bodyFat = 163.205 * Math.log10(diff) - 97.684 * Math.log10(height * 0.393701) + 104.912
  } else {
    bodyFat = -98.42 + 4.15 * (waist / 2.54) - 0.082 * (weight * 2.20462)
    if (bodyFat < 3) bodyFat = 3.0
    else if (bodyFat > 50) bodyFat = 50.0
  }
  bodyFat = pyRound(bodyFat, 2)
  const warning = bodyFat < 2 || bodyFat > 70 ? `\n⚠️ Результат (${pyFloat(bodyFat)}%) кажется необычным. Проверь измерения.` : ''
  await del(chatId, temps.diet_temp)
  await repo.saveBodyFat(userId, bodyFat)
  s.clear()
  const m = await c.reply(`🧮 Процент жира: **${pyFloat(bodyFat)}%**${warning}`, { parse_mode: 'Markdown' })
  temps.body_fat_result = m.message_id
  await showDietMenu(c)
}

async function dietFoodHistoryReply(c) {
  await c.deleteMsg()
  await dropLastMenu(c)
  await deleteTempMessages(c, true)
  c.s.foodHistoryPage = 0
  await showFoodHistoryPage(c)
}

export async function showFoodHistoryPage(c, editMessageId = null) {
  const { s, userId, chatId } = c
  let page = s.foodHistoryPage
  const limit = 3
  const allDates = (await all('SELECT DISTINCT date FROM diet_log WHERE user_id = ? ORDER BY date DESC', [userId])).map(r => r.date)
  const total = allDates.length
  const totalPages = total > 0 ? Math.ceil(total / limit) : 1
  if (page >= totalPages && totalPages > 0) {
    page = totalPages - 1
    s.foodHistoryPage = page
  }
  let text
  if (!total) text = '📖 История еды пока пуста.'
  else {
    const lines = []
    for (const date of allDates.slice(page * limit, Math.min(page * limit + limit, total))) {
      const foods = await all(`SELECT meal_type, food_description, calories, protein, fat, carbs FROM diet_log
        WHERE user_id = ? AND date = ? ORDER BY timestamp`, [userId, date])
      lines.push(`\n📅 ${ddmmyyyy(date)}`)
      let dayCal = 0, has = false
      const dm = { protein: 0, fat: 0, carbs: 0 }
      for (const f of foods) {
        lines.push(`  ${f.meal_type}: ${f.food_description} (${pyInt(f.calories)} ккал)`)
        dayCal += f.calories
        if (f.protein !== null) {
          has = true
          dm.protein += f.protein || 0; dm.fat += f.fat || 0; dm.carbs += f.carbs || 0
        }
      }
      let line = `  🔥 Итого за день: ${pyInt(dayCal)} ккал`
      if (has) line += ` (${formatMacros(dm.protein, dm.fat, dm.carbs)})`
      lines.push(line)
    }
    text = '📖 История еды\n' + lines.join('\n')
  }
  const nav = []
  if (page > 0) nav.push(btn('⬅️ Предыдущая', 'food_history_prev'))
  if (page < totalPages - 1) nav.push(btn('Следующая ➡️', 'food_history_next'))
  const markup = kb(withBack(nav.length ? [nav] : []))
  if (editMessageId) await edit(chatId, editMessageId, text, { reply_markup: markup })
  else {
    const m = await send(chatId, text, { reply_markup: markup })
    s.temps.food_history = m.message_id
  }
  s.navPush('food_history')
}

async function dietChartsReply(c) {
  await c.deleteMsg()
  await dropLastMenu(c)
  await deleteTempMessages(c, true)
  try { await api.sendChatAction({ chat_id: c.chatId, action: 'upload_photo' }) } catch { /* noop */ }
  const w = await one('SELECT COUNT(*) AS n FROM weight_log WHERE user_id = ?', [c.userId])
  const f = await one('SELECT COUNT(*) AS n FROM body_fat_log WHERE user_id = ?', [c.userId])
  const notEnough = async () => {
    await sendTemp(c, '❌ Недостаточно данных для графиков (нужно минимум 2 записи по весу или % жира).')
    await showDietMenu(c)
  }
  if (w.n < 2 && f.n < 2) return notEnough()
  const png = await renderChart('diet', { user_id: c.userId })
  if (!png) return notEnough()
  await sendPhoto(c.userId, png, { caption: '📈 Динамика веса и % жира' })
}

async function startDietSetup(c) {
  c.s.clear()
  c.s.setState(DietState.weight)
  const msg = await c.reply('📝 Введи свой вес (в кг):', { reply_markup: backKeyboard() })
  c.s.temps.diet_setup = msg.message_id
}

async function dietChangeGoalReply(c) {
  await c.deleteMsg()
  await dropLastMenu(c)
  await deleteTempMessages(c, true)
  await startDietSetup(c)
}

/** One step of the profile wizard: validate, store, ask the next question. */
function wizardStep(parse, valid, errText, key, nextState, nextText, nextKb = backKeyboard) {
  return async (c) => {
    const v = parse((c.text || '').trim().replace(',', '.'))
    if (!valid(v)) {
      await c.reply(errText)
      return
    }
    await c.deleteMsg()
    await del(c.chatId, c.s.temps.diet_setup)
    c.s.updateData({ [key]: v })
    c.s.setState(nextState)
    if (nextState === DietState.confirm) return showDietConfirm(c)
    const msg = await c.reply(nextText, { reply_markup: nextKb() })
    c.s.temps.diet_setup = msg.message_id
  }
}

const finite = (lo, hi) => (v) => Number.isFinite(v) && v >= lo && v <= hi

async function dietStepGender(c) {
  await c.deleteMsg()
  c.s.updateData({ gender: c.data === 'gender_male' ? 'мужской' : 'женский' })
  c.s.setState(DietState.activity)
  const msg = await c.reply('🏃 Выбери уровень активности:', { reply_markup: activityKeyboard() })
  c.s.temps.diet_setup = msg.message_id
}

async function dietStepActivity(c) {
  const level = pyFloatParse(c.data.split('_')[1])
  if (Number.isNaN(level)) return c.answer('❌ Ошибка выбора', true)
  await c.deleteMsg()
  c.s.updateData({ activity_level: level })
  c.s.setState(DietState.goal)
  const msg = await c.reply('🎯 Выбери цель:', { reply_markup: goalKeyboard() })
  c.s.temps.diet_setup = msg.message_id
}

async function dietStepGoal(c) {
  const goalType = { goal_loss: 'loss', goal_maintain: 'maintain', goal_gain: 'gain' }[c.data]
  await c.deleteMsg()
  c.s.updateData({ goal_type: goalType })
  if (goalType === 'maintain') {
    c.s.updateData({ target_weight_change: 0.0, target_days: 30 })
    c.s.setState(DietState.confirm)
    await showDietConfirm(c)
  } else {
    c.s.setState(DietState.target_weight)
    const msg = await c.reply(`⚖️ Сколько кг хочешь ${goalType === 'loss' ? 'сбросить' : 'набрать'}? (например, 5):`, { reply_markup: backKeyboard() })
    c.s.temps.diet_setup = msg.message_id
  }
}

const ACTIVITY_LABELS = { 1.2: 'Сидячий', 1.375: 'Лёгкий', 1.55: 'Умеренный', 1.725: 'Высокий', 1.9: 'Очень высокий' }
const GOAL_LABELS = { loss: 'Снижение веса', maintain: 'Поддержание веса', gain: 'Набор массы' }

async function showDietConfirm(c) {
  const d = c.s.getData()
  const change = d.target_weight_change ?? 0.0
  const days = d.target_days ?? 30
  const tdee = repo.calculateTdee(repo.calculateBmr(d.weight, d.height, d.age, d.gender), d.activity_level)
  const [daily, warning] = repo.calculateDailyCalories(tdee, d.goal_type, change, days, d.gender)
  let text = `📋 Проверь данные:

👤 Вес: ${pyFloat(d.weight)} кг | Рост: ${pyFloat(d.height)} см | Возраст: ${d.age} лет
🚻 Пол: ${d.gender} | Активность: ${ACTIVITY_LABELS[d.activity_level] ?? String(d.activity_level)}
🎯 Цель: ${GOAL_LABELS[d.goal_type] ?? d.goal_type}`
  if (d.goal_type !== 'maintain') text += `\n⚖️ Изменение: ${pyFloat(change)} кг за ${days} дней`
  text += `\n\n🔥 Норма калорий: <b>${pyInt(daily)} ккал/день</b>`
  if (warning !== 'ok') text += `\n\n${warning}`
  text += '\n\nВсё верно?'
  c.s.updateData({ daily_calories: daily })
  const msg = await c.reply(text, { parse_mode: 'HTML', reply_markup: dietConfirmKeyboard() })
  c.s.temps.diet_setup = msg.message_id
}

async function dietStepConfirm(c) {
  const d = c.s.getData()
  await c.deleteMsg()
  await repo.saveDietProfile(c.userId, {
    weight: d.weight, height: d.height, age: d.age, gender: d.gender, activity_level: d.activity_level,
    goal_type: d.goal_type, target_weight_change: d.target_weight_change ?? 0.0, target_days: d.target_days ?? 30,
    daily_calories: d.daily_calories,
  })
  c.s.clear()
  await sendTemp(c, '✅ Профиль сохранён!')
  await showDietMenu(c)
}

async function dietStepRestart(c) {
  await c.deleteMsg()
  await startDietSetup(c)
}

const isText = (c) => c.text !== null && c.text !== undefined

export function register() {
  onCallback({ data: 'menu_diet' }, handleDiet)
  onCallback({ data: 'diet_food' }, async (c) => { await c.deleteMsg(); await dietLogFoodStart(c) })
  onCallback({ state: DietState.meal_type, prefix: 'meal_type:' }, dietChooseMeal)
  onCallback({ state: DietState.meal_type, data: 'meal_entry_manual' }, mealEntryManual)
  onCallback({ state: DietState.meal_type, data: 'meal_entry_cancel' }, mealEntryCancel)
  onMessage({ state: DietState.meal_type, when: c => isText(c) && !c.text.startsWith('/') }, mealTypeTextForward)
  onMessage({ state: DietState.meal_type, photo: true }, mealTypePhotoForward)
  onCallback({ state: DietState.food_description, prefix: 'food_choose_' }, dietChooseMyFood)
  onCallback({ state: DietState.food_description, data: 'food_create_new' }, dietCreateNewFood)
  onCallback({ state: DietState.food_description, data: 'food_cancel' }, cancelToDietMenu)
  onMessage({ state: DietState.food_description, photo: true }, processFoodPhoto)
  onMessage({ state: DietState.food_description, when: isText }, processFoodDescription)
  onCallback({ state: DietState.food_confirm, data: 'food_confirm_yes' }, foodConfirmYes)
  onCallback({ data: 'food_add_more_yes' }, foodAddMore)
  onCallback({ state: DietState.food_confirm, data: 'food_confirm_redo' }, foodConfirmRedo)
  onCallback({ state: DietState.food_confirm, data: 'food_confirm_manual' }, foodConfirmManual)
  onMessage({ state: DietState.manual_calories }, manualCalories)
  onCallback({ state: DietState.new_food_name, data: 'save_food_skip' }, saveFoodSkip)
  onCallback({ state: DietState.new_food_name, data: 'save_food_yes' }, saveFoodYesPrompt)
  onMessage({ state: DietState.new_food_name, when: isText }, saveMyFoodName)
  onCallback({ data: 'food_cancel' }, cancelToDietMenu)
  onCallback({ data: 'diet_weight' }, dietLogWeightReply)
  onMessage({ state: DietState.log_weight }, dietLogWeightFinish)
  onCallback({ data: 'diet_bodyfat' }, dietBodyFatReply)
  onMessage({ state: DietState.body_fat_measurements }, dietBodyFatCalculate)
  onCallback({ data: 'diet_food_history' }, dietFoodHistoryReply)
  onCallback({ data: 'food_history_prev' }, async (c) => { if (c.s.foodHistoryPage > 0) c.s.foodHistoryPage = c.s.foodHistoryPage - 1; await showFoodHistoryPage(c, c.msg.message_id) })
  onCallback({ data: 'food_history_next' }, async (c) => { c.s.foodHistoryPage = c.s.foodHistoryPage + 1; await showFoodHistoryPage(c, c.msg.message_id) })
  onCallback({ data: 'back_to_diet' }, cancelToDietMenu)
  onCallback({ data: 'diet_charts' }, dietChartsReply)
  onCallback({ data: 'diet_goal' }, dietChangeGoalReply)
  onMessage({ state: DietState.weight }, wizardStep(pyFloatParse, finite(20, 300), '❌ Введи корректный вес (например, 75.5):',
    'weight', DietState.height, '📝 Введи свой рост (в см):'))
  onMessage({ state: DietState.height }, wizardStep(pyFloatParse, finite(100, 250), '❌ Введи корректный рост (например, 175):',
    'height', DietState.age, '📝 Введи свой возраст (лет):'))
  onMessage({ state: DietState.age }, wizardStep(pyIntParse, finite(10, 120), '❌ Введи корректный возраст (например, 25):',
    'age', DietState.gender, '👤 Укажи пол:', genderKeyboard))
  onCallback({ state: DietState.gender, when: c => c.data === 'gender_male' || c.data === 'gender_female' }, dietStepGender)
  onCallback({ state: DietState.activity, prefix: 'activity_' }, dietStepActivity)
  onCallback({ state: DietState.goal, when: c => ['goal_loss', 'goal_maintain', 'goal_gain'].includes(c.data) }, dietStepGoal)
  onMessage({ state: DietState.target_weight }, wizardStep(pyFloatParse, finite(0.1, 100), '❌ Введи число (например, 5):',
    'target_weight_change', DietState.target_days, '📅 За сколько дней хочешь достичь цели? (например, 90):'))
  onMessage({ state: DietState.target_days }, wizardStep(pyIntParse, finite(7, 730), '❌ Введи число дней от 7 до 730:',
    'target_days', DietState.confirm, ''))
  onCallback({ state: DietState.confirm, data: 'diet_confirm' }, dietStepConfirm)
  onCallback({ state: DietState.confirm, data: 'diet_restart' }, dietStepRestart)
}
