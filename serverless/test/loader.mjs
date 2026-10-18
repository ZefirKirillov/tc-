// Node module hooks: `sdk`, `sdk/*` → the mock, and lib/secrets.js → test values,
// so tests never touch the real Turso database, relay or Bot API.
import { register } from 'node:module'

register('./hooks.mjs', import.meta.url)
