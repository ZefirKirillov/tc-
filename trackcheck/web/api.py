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


@require_user
async def api_tasks_get(request: web.Request):
    from trackcheck.database.repositories import get_all_active_tasks
    user_id = request["tg_user"]["id"]
    tasks = await run_db(get_all_active_tasks, user_id)
    return web.json_response({"ok": True, "data": tasks})


@require_user
async def api_tasks_post(request: web.Request):
    from trackcheck.database.repositories import add_task
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    title = (body.get("title") or "").strip()[:200]
    if not title:
        return web.json_response({"ok": False, "error": "bad_title"}, status=400)
    is_priority = bool(body.get("is_priority", False))
    deadline = (body.get("deadline") or None)
    if deadline:
        try:
            from datetime import datetime as _dt
            _dt.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            return web.json_response({"ok": False, "error": "bad_deadline"}, status=400)
    repeat_days = body.get("repeat_days") or None
    if repeat_days is not None:
        if isinstance(repeat_days, list):
            nums = [str(int(x)) for x in repeat_days if str(x).isdigit() and 0 <= int(x) <= 6]
            repeat_days = ",".join(nums) or None
        elif isinstance(repeat_days, str):
            parts = [p.strip() for p in repeat_days.split(",") if p.strip().isdigit() and 0 <= int(p.strip()) <= 6]
            repeat_days = ",".join(parts) or None
        else:
            return web.json_response({"ok": False, "error": "bad_repeat"}, status=400)
    await run_db(add_task, user_id, title, is_priority, deadline, repeat_days)
    return web.json_response({"ok": True, "data": {"created": True}})


@require_user
async def api_task_done(request: web.Request):
    from trackcheck.database.repositories import complete_task
    user_id = request["tg_user"]["id"]
    try:
        task_id = int(request.match_info.get("task_id", "0"))
    except ValueError:
        return web.json_response({"ok": False, "error": "bad_id"}, status=400)
    await run_db(complete_task, task_id, user_id)
    return web.json_response({"ok": True, "data": {"done": True}})


@require_user
async def api_task_delete(request: web.Request):
    from trackcheck.database.repositories import delete_task
    user_id = request["tg_user"]["id"]
    try:
        task_id = int(request.match_info.get("task_id", "0"))
    except ValueError:
        return web.json_response({"ok": False, "error": "bad_id"}, status=400)
    await run_db(delete_task, task_id, user_id)
    return web.json_response({"ok": True, "data": {"deleted": True}})


@require_user
async def api_diet_get(request: web.Request):
    from trackcheck.database.repositories import (
        get_diet_profile, get_today_calories, get_today_food_log,
    )
    user_id = request["tg_user"]["id"]

    def _load():
        profile = get_diet_profile(user_id)
        log = [
            {"meal": r[0], "description": r[1], "calories": r[2]}
            for r in get_today_food_log(user_id)
        ]
        return {
            "profile": profile,
            "today_calories": get_today_calories(user_id),
            "today_log": log,
        }

    data = await run_db(_load)
    return web.json_response({"ok": True, "data": data})


@require_user
async def api_diet_log_post(request: web.Request):
    from trackcheck.database.repositories import save_food_log
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    description = (body.get("description") or "").strip()[:300]
    try:
        calories = float(body.get("calories", 0))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad_calories"}, status=400)
    if not description or not (0 < calories <= 10000):
        return web.json_response({"ok": False, "error": "bad_params"}, status=400)
    meal = (body.get("meal") or "Еда").strip()[:50]

    def _save():
        save_food_log(user_id, meal, description, calories)
        from trackcheck.database.repositories import get_today_calories as _c
        return {"today_calories": _c(user_id)}

    result = await run_db(_save)
    return web.json_response({"ok": True, "data": result})


@require_user
async def api_workout_get(request: web.Request):
    from trackcheck.database.repositories import (
        get_ai_plan, get_today_plan, get_today_session,
        get_session_exercise_logs, get_weekly_workout_progress,
        get_next_training_day, get_or_create_workout_data,
    )
    user_id = request["tg_user"]["id"]

    def _load():
        plan_data = get_ai_plan(user_id)
        if not plan_data:
            return {"has_plan": False, "workout": get_or_create_workout_data(user_id)}
        today_ex = get_today_plan(plan_data, user_id) or []
        session = get_today_session(user_id)
        logs = get_session_exercise_logs(session["id"]) if session else []
        done_count, week_goal = get_weekly_workout_progress(user_id)
        nxt = get_next_training_day(plan_data, user_id)
        return {
            "has_plan": True,
            "mode": plan_data.get("mode"),
            "goal": plan_data.get("goal"),
            "level": plan_data.get("level"),
            "days_per_week": plan_data.get("days_per_week"),
            "plan": plan_data.get("plan"),
            "today_exercises": today_ex,
            "is_rest_day": len(today_ex) == 0,
            "session": {"id": session["id"], "status": session["status"]} if session else None,
            "logs": [
                {"exercise_name": l["exercise_name"], "status": l["status"],
                 "result": l.get("result"), "planned": l.get("planned")}
                for l in logs
            ],
            "week_progress": {"done": done_count, "goal": week_goal},
            "next": {"date": nxt[0], "day": nxt[1]} if nxt[0] else None,
            "workout": get_or_create_workout_data(user_id),
        }

    data = await run_db(_load)
    return web.json_response({"ok": True, "data": data})


@require_user
async def api_workout_start(request: web.Request):
    """Ensure today's session exists, return it (idempotent)."""
    from trackcheck.database.repositories import get_ai_plan, create_today_session
    user_id = request["tg_user"]["id"]

    def _start():
        plan_data = get_ai_plan(user_id)
        if not plan_data:
            return None
        return create_today_session(user_id, plan_data)

    session = await run_db(_start)
    if not session:
        return web.json_response({"ok": False, "error": "no_workout_today"}, status=404)
    return web.json_response({"ok": True, "data": {"session_id": session["id"], "status": session["status"]}})


@require_user
async def api_workout_log_ex(request: web.Request):
    """Log one exercise: {session_id, exercise (dict), action: done|skip, result?}."""
    import json as _json
    from trackcheck.database.connection import db
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    try:
        session_id = int(body.get("session_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad_session"}, status=400)
    action = (body.get("action") or "").strip()
    if action not in ("done", "skip"):
        return web.json_response({"ok": False, "error": "bad_action"}, status=400)
    ex = body.get("exercise") or {}
    ex_name = (ex.get("exercise") or ex.get("name") or "").strip()[:200]
    if not ex_name:
        return web.json_response({"ok": False, "error": "bad_exercise"}, status=400)

    def _log():
        cur = db.execute(
            "SELECT id FROM ai_workout_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id))
        if not cur.fetchone():
            return None
        if action == "done":
            result = body.get("result") or {
                "sets_done": ex.get("sets"), "reps_done": ex.get("reps"),
                "weight_done": ex.get("weight"), "completed": True}
            db.execute(
                "INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, result_json, status)"
                " VALUES (?, ?, ?, ?, ?, 'done')",
                (session_id, user_id, ex_name, _json.dumps(ex, ensure_ascii=False),
                 _json.dumps(result, ensure_ascii=False)))
        else:
            db.execute(
                "INSERT INTO ai_exercise_logs (session_id, user_id, exercise_name, planned_json, status)"
                " VALUES (?, ?, ?, ?, 'skipped')",
                (session_id, user_id, ex_name, _json.dumps(ex, ensure_ascii=False)))
        db.commit()
        return True

    ok = await run_db(_log)
    if not ok:
        return web.json_response({"ok": False, "error": "bad_session"}, status=404)
    return web.json_response({"ok": True, "data": {"logged": True}})


@require_user
async def api_workout_finish(request: web.Request):
    """Mark session done, bump counters + spark (same as bot _finish_workout, minus AI feedback)."""
    from trackcheck.database.connection import db
    from trackcheck.database.repositories import (
        get_session_exercise_logs, add_workout, add_spark, update_streak,
        get_user_name,
    )
    from trackcheck.utils.dates import user_today_str
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    try:
        session_id = int(body.get("session_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad_session"}, status=400)

    def _finish():
        cur = db.execute(
            "SELECT status FROM ai_workout_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id))
        row = cur.fetchone()
        if not row:
            return None
        today = user_today_str(user_id)
        if row[0] != "done":
            db.execute("UPDATE ai_workout_sessions SET status='done', completed_at=? WHERE id=?",
                       (today, session_id))
            db.commit()
            add_workout(user_id)
            ok, _st, rank_up, _o, new_rank = add_spark(user_id, "workout")
            update_streak(user_id)
        else:
            ok, rank_up, new_rank = False, False, None
        logs = get_session_exercise_logs(session_id)
        done = sum(1 for l in logs if l["status"] == "done")
        skipped = sum(1 for l in logs if l["status"] == "skipped")
        return {"done": done, "skipped": skipped, "spark_awarded": bool(ok),
                "rank_up": bool(rank_up), "new_rank": new_rank,
                "name": get_user_name(user_id)}

    result = await run_db(_finish)
    if result is None:
        return web.json_response({"ok": False, "error": "bad_session"}, status=404)
    return web.json_response({"ok": True, "data": result})


@require_user
async def api_workout_generate(request: web.Request):
    """Generate AI plan (slow: Gemini call in thread). Does NOT save — returns plan for review."""
    from trackcheck.utils.concurrency import run_in_thread
    from trackcheck.services.ai_service import gemini_generate_plan
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    goal = (body.get("goal") or "").strip()[:100]
    level = (body.get("level") or "").strip()[:50]
    try:
        days = int(body.get("days", 3))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad_days"}, status=400)
    notes = (body.get("notes") or "").strip()[:500]
    if not goal or not level or not (1 <= days <= 7):
        return web.json_response({"ok": False, "error": "bad_params"}, status=400)
    _ = user_id  # plan generation doesn't need user context
    plan = await run_in_thread(gemini_generate_plan, goal, level, days, notes)
    if not plan:
        return web.json_response({"ok": False, "error": "ai_failed"}, status=502)
    return web.json_response({"ok": True, "data": {"plan": plan}})


@require_user
async def api_workout_save_plan(request: web.Request):
    from trackcheck.database.repositories import save_ai_plan, delete_all_workout_data
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    plan = body.get("plan")
    if not isinstance(plan, dict) or not plan:
        return web.json_response({"ok": False, "error": "bad_plan"}, status=400)
    mode = (body.get("mode") or "ai").strip()[:10]
    goal = (body.get("goal") or "").strip()[:100]
    level = (body.get("level") or "").strip()[:50]
    try:
        days = int(body.get("days", 3))
    except (TypeError, ValueError):
        days = 3
    days = max(1, min(days, 7))
    cycle_weeks = 1
    try:
        cycle_weeks = max(1, min(int(plan.get("cycle_weeks", 1)), 12))
    except (TypeError, ValueError):
        pass

    def _save():
        delete_all_workout_data(user_id)
        save_ai_plan(user_id, mode, goal, level, days, plan, cycle_weeks)
        return True

    await run_db(_save)
    return web.json_response({"ok": True, "data": {"saved": True}})


@require_user
async def api_workout_history(request: web.Request):
    from trackcheck.database.connection import db
    from trackcheck.database.repositories import get_session_exercise_logs
    import json as _json
    user_id = request["tg_user"]["id"]
    try:
        limit = int(request.query.get("limit", "10"))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 30))

    def _load():
        cur = db.execute(
            "SELECT id, date, session_key, status FROM ai_workout_sessions"
            " WHERE user_id = ? ORDER BY date DESC LIMIT ?",
            (user_id, limit))
        out = []
        for row in cur.fetchall():
            sid, date, skey, status = row[0], row[1], row[2], row[3]
            logs = get_session_exercise_logs(sid)
            out.append({
                "date": date, "session_key": skey, "status": status,
                "done": sum(1 for l in logs if l["status"] == "done"),
                "skipped": sum(1 for l in logs if l["status"] == "skipped"),
            })
        return out

    data = await run_db(_load)
    return web.json_response({"ok": True, "data": data})


@require_user
async def api_ai_ask(request: web.Request):
    """Free-form CheckAI question (slow: Gemini call in thread)."""
    from trackcheck.utils.concurrency import run_in_thread
    from trackcheck.database.repositories import get_user_name, save_last_ai_answer
    from trackcheck.services.ai_service import gemini_generate, get_full_context_for_ai
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    question = (body.get("question") or "").strip()[:2000]
    if len(question) < 3:
        return web.json_response({"ok": False, "error": "too_short"}, status=400)
    tg = request["tg_user"]
    first = tg.get("first_name", "") or ""

    def _context():
        name = get_user_name(user_id, first or "друг")
        ctx = get_full_context_for_ai(user_id)
        return (f"Ты — персональный трекер-ассистент. Пользователь {name}.\n\n"
                f"Вот свежие данные пользователя:\n{ctx}\n\n"
                f"Вопрос: {question}\nОтветь кратко, конкретно, с эмодзи, обращайся по имени.")

    prompt = await run_db(_context)
    answer = await run_in_thread(gemini_generate, prompt, 8192)
    if answer.startswith("❌"):
        return web.json_response({"ok": False, "error": "ai_failed"}, status=502)
    await run_db(save_last_ai_answer, user_id, answer)
    return web.json_response({"ok": True, "data": {"answer": answer}})


@require_user
async def api_ai_advice(request: web.Request):
    """One-tap personal advice (slow: Gemini call in thread)."""
    from trackcheck.utils.concurrency import run_in_thread
    from trackcheck.database.repositories import get_user_name, save_last_ai_answer
    from trackcheck.services.ai_service import gemini_generate, get_full_context_for_ai
    user_id = request["tg_user"]["id"]
    tg = request["tg_user"]
    first = tg.get("first_name", "") or ""

    def _context():
        name = get_user_name(user_id, first or "друг")
        ctx = get_full_context_for_ai(user_id)
        return (f"Ты — персональный трекер-ассистент. Пользователь {name}.\n\n"
                f"Вот свежие данные пользователя:\n{ctx}\n\n"
                "Дай короткий персональный совет (3-5 предложений): что идёт хорошо, "
                "на что обратить внимание, и один конкретный шаг на сегодня/завтра. "
                "Обращайся по имени, используй эмодзи, пиши по-русски.")

    prompt = await run_db(_context)
    answer = await run_in_thread(gemini_generate, prompt, 8192)
    if answer.startswith("❌"):
        return web.json_response({"ok": False, "error": "ai_failed"}, status=502)
    await run_db(save_last_ai_answer, user_id, answer)
    return web.json_response({"ok": True, "data": {"answer": answer}})


@require_user
async def api_ai_last(request: web.Request):
    from trackcheck.database.repositories import get_last_ai_answer
    user_id = request["tg_user"]["id"]
    answer = await run_db(get_last_ai_answer, user_id)
    return web.json_response({"ok": True, "data": {"answer": answer}})


@require_user
async def api_stats_get(request: web.Request):
    from trackcheck.database.repositories import (
        get_daily_ratings, get_or_create_rank_data, get_streak,
        get_or_create_workout_data,
    )
    from trackcheck.services.gamification_service import (
        get_rank_name, get_rank_emoji,
    )
    user_id = request["tg_user"]["id"]
    try:
        days = int(request.query.get("days", "7"))
    except ValueError:
        days = 7
    days = max(1, min(days, 30))

    def _load():
        rows = get_daily_ratings(user_id, days)
        by_date: dict = {}
        for day_date, category, rating in rows:
            by_date.setdefault(day_date, {})[category] = rating
        rank_data = get_or_create_rank_data(user_id)
        return {
            "days": days,
            "daily": [{"date": d, "ratings": r} for d, r in sorted(by_date.items())],
            "rank": {
                **rank_data,
                "name": get_rank_name(rank_data["current_rank"]),
                "emoji": get_rank_emoji(rank_data["current_rank"]),
            },
            "streak": get_streak(user_id),
            "workout": get_or_create_workout_data(user_id),
        }

    data = await run_db(_load)
    return web.json_response({"ok": True, "data": data})


def create_api_app() -> web.Application:
    app = web.Application()
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
    return app
