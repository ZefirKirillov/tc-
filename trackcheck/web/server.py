"""Combined HTTP server: /healthz + /api/* + /app/* on one port."""
import asyncio
import os
import time

from aiohttp import web

from trackcheck.health import HOST, DEFAULT_PORT, healthz, index
from trackcheck.web.api import (
    api_me, api_ratings_get, api_ratings_post,
    api_tasks_get, api_tasks_post, api_task_done, api_task_delete,
    api_diet_get, api_diet_log_post, api_diet_photo, api_diet_estimate, api_diet_profile_post,
    api_body_get, api_body_post, api_stats_get,
    api_workout_get, api_workout_start, api_workout_log_ex,
    api_workout_log_text, api_workout_finish, api_workout_generate,
    api_workout_save_plan, api_workout_parse_plan,
    api_workout_review, api_workout_apply_review,
    api_workout_history, api_ai_ask, api_ai_advice, api_ai_last,
)
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
    app = web.Application(middlewares=[_timing])
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/", index)

    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/ratings", api_ratings_get)
    app.router.add_post("/api/ratings", api_ratings_post)
    app.router.add_get("/api/tasks", api_tasks_get)
    app.router.add_post("/api/tasks", api_tasks_post)
    app.router.add_post("/api/tasks/{task_id}/done", api_task_done)
    app.router.add_delete("/api/tasks/{task_id}", api_task_delete)
    app.router.add_get("/api/diet", api_diet_get)
    app.router.add_post("/api/diet/log", api_diet_log_post)
    app.router.add_post("/api/diet/photo", api_diet_photo)
    app.router.add_post("/api/diet/estimate", api_diet_estimate)
    app.router.add_post("/api/diet/profile", api_diet_profile_post)
    app.router.add_get("/api/body", api_body_get)
    app.router.add_post("/api/body", api_body_post)
    app.router.add_get("/api/stats", api_stats_get)
    app.router.add_get("/api/workout", api_workout_get)
    app.router.add_post("/api/workout/start", api_workout_start)
    app.router.add_post("/api/workout/log", api_workout_log_ex)
    app.router.add_post("/api/workout/log-text", api_workout_log_text)
    app.router.add_post("/api/workout/finish", api_workout_finish)
    app.router.add_post("/api/workout/generate", api_workout_generate)
    app.router.add_post("/api/workout/plan", api_workout_save_plan)
    app.router.add_post("/api/workout/parse-plan", api_workout_parse_plan)
    app.router.add_post("/api/workout/review", api_workout_review)
    app.router.add_post("/api/workout/apply-review", api_workout_apply_review)
    app.router.add_get("/api/workout/history", api_workout_history)
    app.router.add_post("/api/ai/ask", api_ai_ask)
    app.router.add_post("/api/ai/advice", api_ai_advice)
    app.router.add_get("/api/ai/last", api_ai_last)

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
