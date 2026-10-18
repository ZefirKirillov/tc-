// Diff what the user sees in pyref vs jsref output.
//   node compare.mjs py.json js.json
import { readFileSync } from 'node:fs'

const [py, js] = process.argv.slice(2).map(f => JSON.parse(readFileSync(f, 'utf8')))
const ANIM = /^(Думаю\.*|Анализирую\.*|Ищу пишущую ручку\.\.\.|Составляю программу\.\.\.|Подбираю упражнения\.\.\.|Рассчитываю нагрузку\.\.\.|Финальные штрихи\.\.\.|Читаю план\.\.\.|Разбираю структуру\.\.\.|Определяю дни\.\.\.|Считаю подходы\.\.\.|Почти готово\.\.\.|Обновляю план\.*|🔍 Загружаю фото\.\.\.|🔍 Анализирую телосложение\.\.\.|💪 Оцениваю пропорции\.\.\.|📝 Готовлю разбор\.\.\.)$/
// The Mini App moves hosts (Render /app → tgcloud.ai /); only the tab matters.
const appUrl = (u) => { const m = /[?&]tab=(\w+)/.exec(u); return `app:${m ? m[1] : ''}` }
const kbOf = (rm) => (rm?.inline_keyboard || []).map(r => r.map(b => b.callback_data ?? (b.web_app ? appUrl(b.web_app.url) : b.url ?? '?')).join(' | '))
const kbText = (rm) => (rm?.inline_keyboard || []).map(r => r.map(b => b.text).join(' | '))

function visible(calls) {
  const out = []
  for (const c of calls) {
    const p = c.params
    if (c.method === 'sendMessage' || c.method === 'editMessageText') {
      if (ANIM.test(p.text) && !p.reply_markup) continue
      // streaming partials («… ▌») are timing-dependent
      if (c.method === 'editMessageText' && /▌$/.test(p.text || '')) continue
      out.push({ m: c.method === 'sendMessage' ? 'send' : 'edit', text: p.text, parse: p.parse_mode || null, kb: kbOf(p.reply_markup), kbt: kbText(p.reply_markup) })
    } else if (c.method === 'sendPhoto') {
      out.push({ m: 'photo', caption: p.caption })
    } else if (c.method === 'editMessageReplyMarkup') {
      out.push({ m: 'markup', kb: kbOf(p.reply_markup) })
    } else if (c.method === 'answerCallbackQuery' && p.text) {
      out.push({ m: 'toast', text: p.text, alert: !!p.show_alert })
    }
  }
  return out
}

let diffs = 0
const n = Math.max(py.steps.length, js.steps.length)
for (let i = 0; i < n; i++) {
  const a = py.steps[i], b = js.steps[i]
  const va = visible(a?.calls || []), vb = visible(b?.calls || [])
  const sa = JSON.stringify(va), sb = JSON.stringify(vb)
  if (sa !== sb) {
    diffs++
    console.log(`\n=== step ${i}: ${JSON.stringify(a?.step || b?.step)}`)
    const m = Math.max(va.length, vb.length)
    for (let j = 0; j < m; j++) {
      const x = JSON.stringify(va[j]), y = JSON.stringify(vb[j])
      if (x === y) console.log(`   = ${x?.slice(0, 160)}`)
      else { console.log(`  PY ${x}`); console.log(`  JS ${y}`) }
    }
  }
}
const IGNORE_TABLES = new Set([])
for (const t of new Set([...Object.keys(py.db), ...Object.keys(js.db)])) {
  if (IGNORE_TABLES.has(t)) continue
  const norm = (rows) => JSON.stringify((rows || []).map(r => r.map(v => (typeof v === 'number' ? Number(v.toFixed(6)) : v === 'None' ? null : v))))
  // timestamp-ish columns differ by definition
  const strip = (rows) => (rows || []).map(r => r.map(v => (typeof v === 'string' && /^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(v) ? '<ts>' : v)))
  if (norm(strip(py.db[t])) !== norm(strip(js.db[t]))) {
    diffs++
    console.log(`\n=== table ${t}\n  PY ${norm(strip(py.db[t])).slice(0, 600)}\n  JS ${norm(strip(js.db[t])).slice(0, 600)}`)
  }
}
console.log(diffs ? `\n${diffs} difference(s)` : 'identical')
process.exit(diffs ? 1 : 0)
