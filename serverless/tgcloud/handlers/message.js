// Every private-chat message goes through the TrackCheck router.

import { registerAll } from '../lib/bot/index.js'
import { dispatch } from '../lib/router.js'

registerAll()

export default async function (message) {
  await dispatch('message', message)
}
