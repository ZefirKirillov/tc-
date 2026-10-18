# TrackCheck on Telegram Serverless

The bot's handlers and the Mini App run on Telegram Serverless (JavaScript in
`tgcloud/`, hosted by Telegram). The Python app on Render stays for what the
serverless runtime can't do:

| Where | What |
|---|---|
| **Telegram Serverless** (`tgcloud/`) | every bot handler (port of `trackcheck/handlers/`), the Mini App and its API (`endpoints/api.js`, port of `trackcheck/web/api.py`) |
| **Render, `BOT_MODE=worker`** | scheduled jobs (daily ratings at 00:01 / 23:55, reminders), the AI relay, chart rendering |
| **Turso** | all data, unchanged — both sides use the same database |

Why the worker is still needed:

- **GigaChat** can't be reached from Serverless (port 9443 is refused and the
  Russian root CA isn't trusted), so every AI call goes through
  `POST /relay/generate` on Render, which still runs `ai_service.py`.
- **No timers or cron** in Serverless: code only runs when an update arrives.
- **No npm packages**: charts are still drawn by plotly on Render (`/relay/chart`).
- **~30 s per update**: a relay call waits at most ~22 s. A slower AI answer
  comes back as «⏳ ИИ ещё думает…» and the relay keeps working; the existing
  «🔄 Попробовать еще раз» button (same request → same job key) picks it up.

## Layout

```
tgcloud/handlers/   message.js, callback_query.js → lib/router.js
tgcloud/endpoints/  api.js (Mini App API), setup.js (menu button + commands)
tgcloud/lib/        turso.js (Turso over HTTP), session.js (FSM/«Назад»/temp
                    messages in the local DB), repo.js, ai.js, tracker.js,
                    potential.js, workout_service.js, miniapp_api.js
tgcloud/lib/bot/    the handlers, one file per Python module
tgcloud/schema.js   local table `sessions` (UI state only)
test/               harness, Python-vs-JS comparisons, tests
```

`tgcloud/lib/secrets.js` is gitignored but deployed; copy `secrets.example.js`.

## Deploy

```
npm install
npx tgcloud login              # in a real terminal; asks for the bot token
cp secrets.example.js tgcloud/lib/secrets.js   # and fill it in
npm run deploy                 # builds ../miniapp (VITE_BACKEND=serverless) and pushes
npx tgcloud migrate            # first time: creates the `sessions` table
npx tgcloud run endpoints/setup '{ secret: "<RELAY_SECRET>" }' --ctx '{ initData: { user: { id: 0 } } }'
```

`push` prints the Mini App URL — put it into `MINIAPP_BASE_URL` in `secrets.js`
and push again.

Render (worker) env: `BOT_MODE=worker`, `RELAY_SECRET` (same as in
`secrets.js`), `MINIAPP_URL=https://app<id>.tgcloud.ai/`, plus the existing
`BOT_TOKEN`, `TURSO_*` and AI keys. `BOT_MODE=relay` runs only the relay (for a
test bot); without `BOT_MODE` the app is the old all-in-one polling bot.

## Tests

```
npm test            # serverless-specific behaviour + Mini App API
npm run compare     # every scenario in test/scenarios through the Python bot
                    # and the port; diffs what the user sees and the database
python -m pytest test/test_relay.py   # relay (needs the bot's Python deps)
```

`npm run compare` needs a Python 3.12 with `aiogram==3.4.1 apscheduler plotly
Pillow` (`PYTHON=…/bin/python npm run compare`).

## Differences from the Python bot

Intentional:

- Messages the Python bot deleted after a few seconds (confirmations,
  «✨ Новый ранг», the welcome screen) are deleted on the user's next
  interaction instead — there are no timers.
- «Думаю…» animations update every ~2 s (relay heartbeat), Check answers still
  stream into the message.
- In the Mini App, Check answers arrive whole instead of streaming.
- Group chats and messages from bots are ignored.

Python bugs fixed in the port (the comparison scenarios avoid these steps):

- Monthly exercise review: the AI's JSON went through `strip_markdown`, whose
  `_…_` rule ate the underscores in `old_exercise` / `week_1`; the bot crashed
  and the Mini App never saw `no_changes_needed`.
- Body photo «Попробовать ещё раз» after a failure: `state.clear()` dropped the
  photo, so the retry could never succeed.
- «Удалить упражнение» offered «Пропустить →» instead of «Да, удалить».
