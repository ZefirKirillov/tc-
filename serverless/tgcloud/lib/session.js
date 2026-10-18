// Per-user UI state, stored in the platform's local database (fast, no
// network). Replaces trackcheck/runtime.py's in-memory dicts and aiogram's
// MemoryStorage FSM — which also means it now survives restarts.

import { db } from 'sdk'
import { eq } from 'sdk/db'
import { sessions } from '../schema.js'

function empty() {
  return {
    fsm: { state: null, data: {} },
    nav: [],            // runtime.user_nav
    temps: {},          // runtime.user_temp_messages
    lastMenu: null,     // runtime.user_last_menu
    historyPage: 0,     // runtime.user_history_page
    foodHistoryPage: 0, // runtime.user_food_history_page
    welcomeMsg: null,   // runtime.user_welcome_message
    later: [],          // [chat_id, message_id] to delete on the next interaction
  }
}

export class Session {
  constructor(userId, data) {
    this.userId = userId
    this.d = { ...empty(), ...(data || {}) }
    this._saved = JSON.stringify(this.d)
  }

  // ---- FSM (aiogram FSMContext) ----
  getState() { return this.d.fsm.state }
  setState(state) { this.d.fsm.state = state || null }
  getData() { return { ...this.d.fsm.data } }
  updateData(patch) { Object.assign(this.d.fsm.data, patch) }
  setData(data) { this.d.fsm.data = { ...data } }
  clear() { this.d.fsm = { state: null, data: {} } }

  // ---- navigation stack ----
  navPush(screen) {
    const s = this.d.nav
    if (!s.length || s[s.length - 1] !== screen) s.push(screen)
    if (s.length > 50) s.splice(0, s.length - 50)
  }
  navCurrent() {
    const s = this.d.nav
    return s.length ? s[s.length - 1] : 'main'
  }
  navPop() {
    if (this.d.nav.length) this.d.nav.pop()
    return this.navCurrent()
  }

  // ---- temp messages ----
  get temps() { return this.d.temps }
  set temps(v) { this.d.temps = v || {} }

  get lastMenu() { return this.d.lastMenu }
  set lastMenu(v) { this.d.lastMenu = v ?? null }

  get historyPage() { return this.d.historyPage || 0 }
  set historyPage(v) { this.d.historyPage = v || 0 }

  get foodHistoryPage() { return this.d.foodHistoryPage || 0 }
  set foodHistoryPage(v) { this.d.foodHistoryPage = v || 0 }

  get welcomeMsg() { return this.d.welcomeMsg }
  set welcomeMsg(v) { this.d.welcomeMsg = v ?? null }

  /** Delete this message on the user's next interaction (no timers here). */
  deleteLater(chatId, messageId) {
    if (messageId) this.d.later.push([chatId, messageId])
  }
  takeLater() {
    const l = this.d.later
    this.d.later = []
    return l
  }

  get dirty() { return JSON.stringify(this.d) !== this._saved }
}

export async function loadSession(userId) {
  const row = await db.select().from(sessions).where(eq(sessions.userId, userId)).get()
  return new Session(userId, row ? row.data : null)
}

export async function saveSession(s) {
  if (!s.dirty) return
  const now = Math.floor(Date.now() / 1000)
  await db.insert(sessions).values({ userId: s.userId, data: s.d, updatedAt: now })
    .onConflictDoUpdate({ target: sessions.userId, set: { data: s.d, updatedAt: now } })
  s._saved = JSON.stringify(s.d)
}
