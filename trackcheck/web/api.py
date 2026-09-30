"""JSON API for the Telegram Mini App.

All /api/* routes require Telegram initData auth (see auth.py).
DB access goes through run_db() so Turso network calls never block the loop.
"""
import json

from aiohttp import web

from trackcheck.utils.concurrency import run_db
from trackcheck.web.auth import validate_init_data


def _unauthorized():
    return web.json_response({"ok": False, "error": "unauthorized"}, status=401)


async def _current_user(request: web.Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data and request.method in ("GET", "DELETE"):
        init_data = request.query.get("initData", "")
    if not init_data and request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
            init_data = body.get("_initData", "") if isinstance(body, dict) else ""
        except Exception:
            init_data = ""
    user = validate_init_data(init_data) if init_data else None
    return user


def require_user(handler):
    async def wrapper(request: web.Request):
        user = await _current_user(request)
        if not user:
            return _unauthorized()
        request["tg_user"] = user
        return await handler(request)
    return wrapper


@require_user
async def api_me(request: web.Request):
    from trackcheck.database.repositories import (
        get_user_name, get_today_ratings, get_or_create_workout_data,
        get_or_create_rank_data, get_streak, get_diet_profile,
        get_today_calories,
    )
    from trackcheck.services.gamification_service import (
        get_rank_name, get_rank_emoji, get_sparks_for_next_rank,
    )
    user_id = request["tg_user"]["id"]

    def _load():
        rank_data = get_or_create_rank_data(user_id)
        rank_id = rank_data["current_rank"]
        sparks_needed, next_total = get_sparks_for_next_rank(rank_id, rank_data["total_sparks"])
        profile = get_diet_profile(user_id)
        return {
            "id": user_id,
            "name": get_user_name(user_id),
            "today_ratings": get_today_ratings(user_id),
            "workout": get_or_create_workout_data(user_id),
            "rank": {
                **rank_data,
                "name": get_rank_name(rank_id),
                "emoji": get_rank_emoji(rank_id),
                "sparks_needed": sparks_needed,
                "next_total": next_total,
            },
            "streak": get_streak(user_id),
            "diet": {
                "configured": profile is not None,
                "today_calories": get_today_calories(user_id) if profile else 0,
                "daily_goal": profile["daily_calories"] if profile else 0,
            },
        }

    data = await run_db(_load)
    return web.json_response({"ok": True, "data": data})


@require_user
async def api_ratings_get(request: web.Request):
    from trackcheck.database.repositories import get_today_ratings
    user_id = request["tg_user"]["id"]
    ratings = await run_db(get_today_ratings, user_id)
    return web.json_response({"ok": True, "data": ratings})


@require_user
async def api_ratings_post(request: web.Request):
    from trackcheck.database.repositories import (
        save_rating, save_user_settings, update_streak,
        check_all_categories_completed, add_spark,
    )
    from trackcheck.utils.dates import user_today_str
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    category = (body.get("category") or "").strip()
    try:
        rating = int(body.get("rating"))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad_rating"}, status=400)
    valid = ("сон", "еда", "активность", "зависание", "настрой")
    if category not in valid or not (1 <= rating <= 10):
        return web.json_response({"ok": False, "error": "bad_params"}, status=400)
    tg = request["tg_user"]
    first = tg.get("first_name", "") or ""
    uname = tg.get("username", "") or ""

    def _save():
        save_user_settings(user_id, uname, first)
        update_streak(user_id)
        save_rating(user_id, category, rating, user_today_str(user_id))
        spark_awarded = False
        if check_all_categories_completed(user_id):
            ok, *_ = add_spark(user_id, "categories")
            spark_awarded = bool(ok)
        from trackcheck.database.repositories import get_today_ratings as _g
        return {"ratings": _g(user_id), "spark_awarded": spark_awarded}

    result = await run_db(_save)
    return web.json_response({"ok": True, "data": result})


def create_api_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/ratings", api_ratings_get)
    app.router.add_post("/api/ratings", api_ratings_post)
    return app
