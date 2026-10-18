import { readFileSync } from 'node:fs'
const [py, js] = process.argv.slice(2).map(f => JSON.parse(readFileSync(f, 'utf8')))
// floats: Python 80.0 vs JS 80 are the same JSON number; created_at timestamps differ by definition
const norm = (v) => JSON.stringify(v, (k, x) => (k === 'created_at' ? '<ts>' : typeof x === 'number' ? Number(x.toFixed(6)) : x))
let diffs = 0
for (let i = 0; i < Math.max(py.length, js.length); i++) {
  const a = py[i], b = js[i]
  if (a?.status !== b?.status || norm(a?.body) !== norm(b?.body)) {
    diffs++
    console.log(`\n=== ${JSON.stringify(a?.call || b?.call).slice(0, 200)}`)
    console.log(`  PY ${a?.status} ${norm(a?.body).slice(0, 700)}`)
    console.log(`  JS ${b?.status} ${norm(b?.body).slice(0, 700)}`)
  }
}
console.log(diffs ? `\n${diffs} difference(s)` : 'identical')
process.exit(diffs ? 1 : 0)
