import { readFileSync } from 'node:fs'
import { buildSeries, findSegments, segmentSignature, fallbackNote, notePrompt } from '../tgcloud/lib/potential.js'
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'))
let bad = 0, segs = 0
for (const c of cases) {
  const series = buildSeries(c.dates, c.by, c.body)
  if (JSON.stringify(series) !== JSON.stringify(c.series)) { bad++; console.log('series differ', JSON.stringify(series).slice(0, 300), '\n', JSON.stringify(c.series).slice(0, 300)); continue }
  const out = []
  for (const s of findSegments(series)) out.push({ ...s, signature: await segmentSignature(series, s), fallback: fallbackNote(series, s), prompt: notePrompt('Тест', series, s) })
  segs += out.length
  if (JSON.stringify(out) !== JSON.stringify(c.segments)) { bad++; console.log('segments differ\n JS', JSON.stringify(out).slice(0, 600), '\n PY', JSON.stringify(c.segments).slice(0, 600)) }
}
console.log(bad ? `${bad} case(s) differ` : `identical (${cases.length} cases, ${segs} segments)`)
process.exit(bad ? 1 : 0)
