import { table, integer, json } from 'sdk/db';

// Durable data lives in Turso (lib/turso.js). This local database only holds
// per-user UI state that the Python bot kept in process memory: dialog (FSM)
// state, the "Назад" stack, ids of messages to clean up, list pages.
export const sessions = table('sessions', {
  userId: integer('user_id').primaryKey(),
  data: json('data').notNull(),
  updatedAt: integer('updated_at').notNull(),
});
