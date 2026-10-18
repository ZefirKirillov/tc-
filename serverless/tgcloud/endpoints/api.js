// The Mini App's whole API behind one endpoint: the front-end sends
// { method, path, body } exactly as it used to send HTTP requests to Render,
// and gets back { status, body } — the same JSON the aiohttp routes returned.

import { handleApi } from '../lib/miniapp_api.js'

export default async function (input, ctx) {
  const user = ctx.initData.user
  try {
    return await handleApi(user, input)
  } catch (e) {
    console.error('[API]', input && input.method, input && input.path, e)
    return { status: 500, body: { ok: false, error: 'internal', message: 'Сервер временно недоступен. Попробуй позже.' } }
  }
}
