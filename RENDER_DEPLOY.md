# TrackCheck on Render (free tier) — Web Service + external uptime monitor

This bot runs Telegram long-polling, so the process must stay alive around
the clock. On Render's free tier an idle service is suspended ("spun down");
after suspension nothing inside the process (including any self-ping loop)
can wake it up again. The fix is an **external** monitor that keeps hitting
an HTTP endpoint.

## 1. Deploy as a Web Service, NOT a Background Worker

Render Background Workers do not expose an inbound HTTP port, so Render (and
UptimeRobot) could not reach the health-check. Deploy TrackCheck as a
**Web Service** so the port below is reachable from the internet.

## 2. Start command (Render → Settings → Start Command)

```
python ctx.py
```

No Procfile or Dockerfile is required. The app reads the port itself (see 3).

## 3. Endpoints

The bot starts a tiny aiohttp server alongside Telegram polling:

- `GET /healthz` → HTTP 200, JSON body exactly `{"status":"ok"}`
- `GET /` → HTTP 200, plain text `TrackCheck is running`

Port handling: the server binds `0.0.0.0` and reads the port from the `PORT`
environment variable Render injects (`10000` is only the local-development
fallback). Never hardcode a Render URL, service name, or secret in code.

## 4. Health-check URL

```
https://<your-render-service>.onrender.com/healthz
```

Replace `<your-render-service>` with the service name shown in the Render
dashboard (e.g. `https://trackcheck.onrender.com/healthz`).

## 5. External monitor (required — every 5 minutes)

There is intentionally **no self-ping** in this codebase: after Render
suspends the process, in-process timers no longer run, so self-ping cannot
prevent spin-down. Configure an external monitor instead:

1. Create a free [UptimeRobot](https://uptimerobot.com) account.
2. Add monitor type **HTTP(s)**, pointing at the `/healthz` URL above.
3. Set the monitoring interval to **5 minutes** (the recommended value;
   Render's free tier suspends a service after ~15 minutes without traffic,
   so a 5-minute cadence keeps it warm with margin).
4. Keep the default "alert when down" contacts so you are notified of real
   outages.

Any equivalent external cron/ping service works; only the "external,
every 5 minutes" part matters.

## 6. What `/healthz` does (and does not) prove

- It proves the Python process is alive and accepting HTTP requests.
- It does **not** guarantee Telegram polling, Gemini, or Turso are healthy:
  the handler is dependency-free by design and never calls Telegram, Gemini,
  Turso, or the database, so it keeps returning 200 even if one of those
  backends is temporarily unavailable. Check BotFather/Telegram and the bot
  logs if the bot itself stops responding while `/healthz` is green.
