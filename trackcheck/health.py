"""Minimal HTTP health-check for external uptime monitors.

Render's free tier suspends idle Web Services; an EXTERNAL monitor must GET
/healthz every few minutes to keep the process alive. There is intentionally
NO internal self-ping loop: self-ping cannot wake a process Render already
suspended.

Handlers are dependency-free on purpose: they never touch Telegram, Gemini,
Turso or the database, so they stay fast and return 200 even when an
optional external backend is temporarily unavailable.

Requires `aiohttp`, which is already a transitive dependency via aiogram
(aiogram 3.x serves Bot API traffic through aiohttp), so no new entry in
requirements.txt is needed.
"""
import os

from aiohttp import web

HOST = "0.0.0.0"
DEFAULT_PORT = 10000
HEALTH_BODY = {"status": "ok"}
ROOT_TEXT = "TrackCheck is running"


def get_port() -> int:
    return int(os.getenv("PORT", "10000"))


async def healthz(request):
    return web.json_response(HEALTH_BODY)


async def index(request):
    return web.Response(text=ROOT_TEXT)


def create_health_app():
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/", index)
    return app


async def start_health_server():
    """Bind HOST:get_port() and return the AppRunner.

    The caller owns the runner and must `await runner.cleanup()` on
    shutdown (see trackcheck/app.py).
    """
    port = get_port()
    runner = web.AppRunner(create_health_app())
    await runner.setup()
    await web.TCPSite(runner, HOST, port).start()
    print(f"[BOOT] Health-check слушает {HOST}:{port} (/healthz)")
    return runner
