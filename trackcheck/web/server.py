"""Combined HTTP server: /healthz + /api/* + /app/* on one port."""
import os

from aiohttp import web

from trackcheck.health import HOST, DEFAULT_PORT, healthz, index
from trackcheck.web.api import (
    api_me, api_ratings_get, api_ratings_post,
    api_tasks_get, api_tasks_post, api_task_done, api_task_delete,
    api_diet_get, api_diet_log_post, api_stats_get,
    api_workout_get, api_workout_start, api_workout_log_ex,
    api_workout_finish, api_workout_generate, api_workout_save_plan,
    api_workout_history, api_ai_ask, api_ai_advice, api_ai_last,
)
from trackcheck.web.static_serve import register_static


def create_web_app() -> web.Application:
    app = web.Application()
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
    app.router.add_get("/api/stats", api_stats_get)
    app.router.add_get("/api/workout", api_workout_get)
    app.router.add_post("/api/workout/start", api_workout_start)
    app.router.add_post("/api/workout/log", api_workout_log_ex)
    app.router.add_post("/api/workout/finish", api_workout_finish)
    app.router.add_post("/api/workout/generate", api_workout_generate)
    app.router.add_post("/api/workout/plan", api_workout_save_plan)
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
    return runner
