// Handler registration, in the order of trackcheck/handlers/__init__.py:
// the first matching handler wins, exactly as with aiogram.

import * as screens from './screens.js'
import * as dashboard from './dashboard.js'
import * as categories from './categories.js'
import * as ai from './ai.js'
import * as start from './start.js'
import * as workouts from './workouts.js'
import * as food from './food.js'
import * as stats from './stats.js'
import * as tasks from './tasks.js'
import * as notify from './notify.js'

let registered = false

export function registerAll() {
  if (registered) return
  registered = true
  for (const m of [screens, dashboard, categories, ai, start, workouts, food, stats, tasks, notify]) m.register()
}
