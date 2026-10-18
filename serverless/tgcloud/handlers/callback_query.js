// Inline-button presses.

import { registerAll } from '../lib/bot/index.js'
import { dispatch } from '../lib/router.js'

registerAll()

export default async function (callbackQuery) {
  await dispatch('callback_query', callbackQuery)
}
