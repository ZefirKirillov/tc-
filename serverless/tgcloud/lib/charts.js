// Charts are drawn by the Render worker with the same plotly code as before
// (no plotly here). Returns PNG bytes, or null when there is nothing to draw.

import { fetch } from 'sdk'
import { RELAY_URL, RELAY_SECRET } from './secrets.js'

export async function renderChart(kind, params) {
  try {
    const res = await fetch(`${RELAY_URL.replace(/\/+$/, '')}/relay/chart`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Relay-Secret': RELAY_SECRET },
      body: JSON.stringify({ kind, ...params }),
    })
    if (res.status === 404) return null
    if (!res.ok) throw new Error(`relay chart http ${res.status}: ${(await res.text()).slice(0, 200)}`)
    const chunks = []
    let n = 0
    for await (const chunk of res.body) { chunks.push(chunk); n += chunk.length }
    const out = new Uint8Array(n)
    let o = 0
    for (const ch of chunks) { out.set(ch, o); o += ch.length }
    return out
  } catch (e) {
    console.error('[CHART]', e && e.message)
    throw e
  }
}
