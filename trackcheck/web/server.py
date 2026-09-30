"""Combined HTTP server: /healthz + /api/* + /app/* on one port."""
import os

from aiohttp import web

from trackcheck.health import HOST, DEFAULT_PORT, healthz, index
from trackcheck.web.api import api_me, api_ratings_get, api_ratings_post
from trackcheck.web.static_serve import register_static


def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/", index)

    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/ratings", api_ratings_get)
    app.router.add_post("/api/ratings", api_ratings_post)

    register_static(app)  # /app static + SPA fallback, registered last
    return app


async def start_web_server():
    """Drop-in replacement for start_health_server(). Same host/port contract."""
    port = int(os.getenv("PORT", str(DEFAULT_PORT)))
    runner = web.AppRunner(create_web_app())
    await runner.setup()
    await web.TCPSite(runner, HOST, port).start()
    print(f"[BOOT] Web слушает {HOST}:{port} (/healthz, /api, /app)")
    return runner
