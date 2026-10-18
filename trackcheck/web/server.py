"""Combined HTTP server: /healthz + /api/* + /app/* on one port."""
import asyncio
import os
import time

from aiohttp import web

from trackcheck.health import HOST, DEFAULT_PORT, healthz, index
from trackcheck.web.api import MAX_UPLOAD_BYTES, register_api_routes
from trackcheck.web.relay import register_relay_routes
from trackcheck.web.static_serve import register_static


# Диагностика скорости Mini App (stdout → Render logs). API_SLOW_MS=0 выключает.
_API_SLOW_MS = float(os.getenv("API_SLOW_MS", "300"))
_LOOP_LAG_MS = float(os.getenv("LOOP_LAG_MS", "200"))
_bg_tasks: set = set()


@web.middleware
async def _timing(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    t = time.perf_counter()
    status = 500
    try:
        resp = await handler(request)
        status = resp.status
        return resp
    finally:
        ms = (time.perf_counter() - t) * 1000
        if _API_SLOW_MS > 0 and ms >= _API_SLOW_MS:
            print(f"[API-SLOW] {request.method} {request.path} {status} {ms:.0f}ms", flush=True)


async def _watch_loop_lag():
    """Если event loop заблокирован синхронным кодом (например, запросом к БД
    прямо в async-хендлере), этот тик просыпается с опозданием — логируем на сколько.
    Во время блокировки стоят и бот, и все запросы Mini App."""
    interval = 0.1
    while True:
        t = time.perf_counter()
        await asyncio.sleep(interval)
        lag = (time.perf_counter() - t - interval) * 1000
        if lag >= _LOOP_LAG_MS:
            print(f"[LOOP-LAG] event loop был заблокирован ~{lag:.0f}ms", flush=True)


def create_web_app() -> web.Application:
    app = web.Application(middlewares=[_timing], client_max_size=MAX_UPLOAD_BYTES)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/", index)

    register_api_routes(app)
    register_relay_routes(app)

    register_static(app)  # /app static + SPA fallback, registered last
    return app


async def start_web_server():
    """Drop-in replacement for start_health_server(). Same host/port contract."""
    port = int(os.getenv("PORT", str(DEFAULT_PORT)))
    runner = web.AppRunner(create_web_app())
    await runner.setup()
    await web.TCPSite(runner, HOST, port).start()
    print(f"[BOOT] Web слушает {HOST}:{port} (/healthz, /api, /app)")
    if _LOOP_LAG_MS > 0:
        _bg_tasks.add(asyncio.create_task(_watch_loop_lag()))  # strong ref: loop keeps only weak ones
    return runner
