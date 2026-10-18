// One-off: the chat menu button («TrackCheck» → Mini App) and the command list,
// which the Python bot set on every start. Run it after a deploy:
//   npx tgcloud run endpoints/setup '{ secret: "<RELAY_SECRET>" }' --ctx '{ initData: { user: { id: 0 } } }'
// Any Mini App user could call a deployed endpoint, hence the secret.

import { api, EndpointError } from 'sdk'
import { RELAY_SECRET } from '../lib/secrets.js'
import { MINIAPP_URL } from '../lib/config.js'

export default async function (input) {
  if (!input || input.secret !== RELAY_SECRET) throw new EndpointError('forbidden', { code: 'FORBIDDEN' })
  await api.setChatMenuButton({ menu_button: { type: 'web_app', text: 'TrackCheck', web_app: { url: MINIAPP_URL } } })
  await api.setMyCommands({ commands: [
    { command: 'app', description: 'Открыть приложение' },
    { command: 'start', description: 'Главное меню' },
    { command: 'timezone', description: 'Часовой пояс' },
  ] })
  return { ok: true, miniapp: MINIAPP_URL }
}
