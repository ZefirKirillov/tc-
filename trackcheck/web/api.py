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


# Russian user-facing error texts for API error codes (frontend falls back to these).
RU_ERRORS = {
    "unauthorized": "Открой через Telegram — кнопка Mini App.",
    "bad_json": "Не получилось прочитать запрос. Попробуй ещё раз.",
    "bad_params": "Некорректные данные. Проверь ввод.",
    "bad_rating": "Оценка должна быть от 1 до 10.",
    "bad_title": "Название задачи не может быть пустым.",
    "bad_deadline": "Дедлайн — дата в формате ГГГГ-ММ-ДД.",
    "bad_repeat": "Дни повтора: числа 0–6 (Пн–Вс).",
    "bad_id": "Некорректный ID.",
    "bad_calories": "Калории — число больше нуля.",
    "bad_session": "Тренировка не найдена. Начни заново.",
    "bad_action": "Неизвестное действие.",
    "bad_exercise": "Не получилось распознать упражнение.",
    "bad_plan": "План пустой или повреждён.",
    "bad_days": "Дней в неделю: от 1 до 7.",
    "too_short": "Напиши чуть подробнее (от 3 символов).",
    "no_workout_today": "Сегодня отдых — тренировки нет.",
    "ai_failed": "❌ ИИ не ответил. Попробуй ещё раз.",
    "photo_too_big": "Фото слишком большое (макс 5 МБ).",
    "photo_bad": "Не получилось прочитать фото.",
    "bad_weight": "Вес: число от 20 до 400 кг.",
    "bad_fat": "Процент жира: число от 1 до 70.",
    "bad_text": "Текст слишком короткий или пустой.",
    "auto_category": "Еда и активность оцениваются автоматически — по калориям и тренировке.",
    "no_diet_profile": "Сначала задай норму калорий.",
    "bad_profile": "Проверь данные: вес 20–300 кг, рост 100–250 см, возраст 10–120.",
    "bad_target": "Цель: от 0,1 до 100 кг за 7–730 дней.",
}


def _err(code: str, status: int = 400):
    return web.json_response({"ok": False, "error": code, "message": RU_ERRORS.get(code, code)}, status=status)


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
    from trackcheck.services.tracker_service import AUTO_CATEGORIES
    if category in AUTO_CATEGORIES:
        return _err("auto_category")
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
        from trackcheck.database.repositories import get_diet_profile, get_today_calories as _c
        from trackcheck.services.tracker_service import sync_diet_rating_for_today
        if not get_diet_profile(user_id):
            return None  # дневник питания работает только с заданной нормой калорий
        save_food_log(user_id, meal, description, calories)
        sync_diet_rating_for_today(user_id)
        return {"today_calories": _c(user_id)}

    result = await run_db(_save)
    if result is None:
        return _err("no_diet_profile")
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
        from trackcheck.services.tracker_service import sync_activity_rating_for_today
        sync_activity_rating_for_today(user_id)
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
async def api_body_get(request: web.Request):
    """Weight + body-fat: last values for the Diet tab."""
    from trackcheck.database.repositories import get_last_weight
    from trackcheck.database.connection import db
    user_id = request["tg_user"]["id"]

    def _load():
        weight = get_last_weight(user_id)
        cur = db.execute(
            "SELECT body_fat FROM body_fat_log WHERE user_id = ? ORDER BY date DESC LIMIT 1",
            (user_id,))
        row = cur.fetchone()
        return {"weight": weight, "body_fat": row[0] if row else None}

    data = await run_db(_load)
    return web.json_response({"ok": True, "data": data})


@require_user
async def api_body_post(request: web.Request):
    """Log weight and/or body fat: {weight?, body_fat?}."""
    from trackcheck.database.repositories import save_weight_log, save_body_fat
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return _err("bad_json")
    weight = body.get("weight")
    fat = body.get("body_fat")
    if weight is None and fat is None:
        return _err("bad_params")
    try:
        weight = float(weight) if weight is not None else None
        fat = float(fat) if fat is not None else None
    except (TypeError, ValueError):
        return _err("bad_params")
    if weight is not None and not (20 <= weight <= 400):
        return _err("bad_weight")
    if fat is not None and not (1 <= fat <= 70):
        return _err("bad_fat")

    def _save():
        if weight is not None:
            save_weight_log(user_id, weight)
        if fat is not None:
            save_body_fat(user_id, fat)
        return {"saved": True}

    result = await run_db(_save)
    return web.json_response({"ok": True, "data": result})


@require_user
async def api_diet_profile_post(request: web.Request):
    """Calorie goal setup — same questions, ranges and formulas as the bot's diet setup
    (Mifflin–St Jeor × activity, goal adjustment with safety limits).
    {weight, height, age, gender: male|female, activity, goal: loss|maintain|gain,
     change?, days?, preview?: bool} → {daily_calories, warning, saved}"""
    import math
    from trackcheck.database.repositories import (
        calculate_bmr, calculate_tdee, calculate_daily_calories, save_diet_profile,
    )
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return _err("bad_json")
    try:
        weight = float(body.get("weight"))
        height = float(body.get("height"))
        age = int(body.get("age"))
        activity = float(body.get("activity"))
    except (TypeError, ValueError):
        return _err("bad_profile")
    gender = {"male": "мужской", "female": "женский"}.get(body.get("gender"))
    goal = body.get("goal")
    if (not all(math.isfinite(x) for x in (weight, height, activity))
            or not 20 <= weight <= 300 or not 100 <= height <= 250 or not 10 <= age <= 120
            or gender is None or activity not in (1.2, 1.375, 1.55, 1.725, 1.9)
            or goal not in ("loss", "maintain", "gain")):
        return _err("bad_profile")
    change, days = 0.0, 30
    if goal != "maintain":
        try:
            change = float(body.get("change"))
            days = int(body.get("days"))
        except (TypeError, ValueError):
            return _err("bad_target")
        if not math.isfinite(change) or not 0.1 <= change <= 100 or not 7 <= days <= 730:
            return _err("bad_target")

    def _calc_and_save():
        tdee = calculate_tdee(calculate_bmr(weight, height, age, gender), activity)
        daily, warning = calculate_daily_calories(tdee, goal, change, days, gender)
        if not body.get("preview"):
            save_diet_profile(user_id=user_id, weight=weight, height=height, age=age, gender=gender,
                              activity_level=activity, goal_type=goal, target_weight_change=change,
                              target_days=days, daily_calories=daily)
        return {"daily_calories": round(daily), "warning": None if warning == "ok" else warning,
                "saved": not body.get("preview")}

    data = await run_db(_calc_and_save)
    return web.json_response({"ok": True, "data": data})


@require_user
async def api_diet_photo(request: web.Request):
    """Analyze food photo → {description, calories}. Does NOT log — client confirms first."""
    import io
    import re
    from trackcheck.utils.concurrency import run_in_thread
    from trackcheck.services.ai_service import analyze_food_photo
    from trackcheck.database.repositories import get_diet_profile
    if not await run_db(get_diet_profile, request["tg_user"]["id"]):
        return _err("no_diet_profile")
    try:
        post = await request.post()
    except Exception:
        return _err("bad_json")
    field = post.get("photo")
    if field is None:
        return _err("photo_bad")
    try:
        image_bytes = field.file.read() if hasattr(field, "file") else bytes(field)
    except Exception:
        return _err("photo_bad")
    if not image_bytes:
        return _err("photo_bad")
    if len(image_bytes) > 5 * 1024 * 1024:
        return _err("photo_too_big")
    # Normalize to PNG (same as bot food.py) to keep model input stable.
    try:
        from PIL import Image
        image = Image.open(io.BytesIO(image_bytes))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        image_bytes = buf.getvalue()
    except Exception:
        pass  # send raw bytes; model layer will fail gracefully → ai_failed
    prompt = (
        "Посмотри на фото еды и оцени калорийность.\n\n"
        "Ответь строго в формате: [название блюда] [число ккал]\n"
        "Название — 1-4 слова на русском. Число — только целые ккал без единиц.\n\n"
        "Правила оценки:\n"
        "- Считай реальную порцию на фото, не занижай\n"
        "- Учитывай видимые соусы, масло, хлеб рядом\n"
        "- Если несколько блюд — суммируй всё\n\n"
        "Примеры правильных ответов:\n"
        "гречка с курицей 480\nпаста карбонара 650\nсалат цезарь 520"
    )
    text = await run_in_thread(analyze_food_photo, image_bytes, prompt)
    if text is None:
        return _err("ai_failed", 502)
    description, calories = "Блюдо на фото", None
    nums = re.findall(r"\b(\d{2,5})\b", text)
    valid = [float(n) for n in nums if 50 <= float(n) <= 9999]
    if valid:
        calories = valid[-1]
    match = re.search(r"^([^0-9]+?)(?:\s*\d|$)", text)
    if match:
        desc = match.group(1).strip(" .,;:-")
        if 2 <= len(desc) <= 50:
            description = desc
    if calories is None or not (0 < calories <= 5000):
        return web.json_response({"ok": True, "data": {
            "description": description, "calories": None, "needs_manual": True, "raw": text[:200]}})
    return web.json_response({"ok": True, "data": {
        "description": description, "calories": int(calories), "needs_manual": False}})


@require_user
async def api_workout_parse_plan(request: web.Request):
    """Parse user-pasted plan text via Gemini → plan JSON for review (no save)."""
    from trackcheck.utils.concurrency import run_in_thread
    from trackcheck.services.ai_service import gemini_parse_manual_plan, _fallback_parse_plan
    try:
        body = await request.json()
    except Exception:
        return _err("bad_json")
    raw_text = (body.get("text") or "").strip()
    if len(raw_text) < 10:
        return _err("bad_text")
    if len(raw_text) > 20000:
        raw_text = raw_text[:20000]
    plan = await run_in_thread(gemini_parse_manual_plan, raw_text)
    if not plan:
        plan = await run_in_thread(_fallback_parse_plan, raw_text)
    if not plan:
        return _err("ai_failed", 502)
    return web.json_response({"ok": True, "data": {"plan": plan}})


@require_user
async def api_workout_log_text(request: web.Request):
    """Log exercise from free text: {session_id, exercise, text} → Gemini parses result."""
    import json as _json
    from trackcheck.database.connection import db
    from trackcheck.utils.concurrency import run_in_thread
    from trackcheck.services.ai_service import gemini_parse_exercise_result
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return _err("bad_json")
    try:
        session_id = int(body.get("session_id", 0))
    except (TypeError, ValueError):
        return _err("bad_session")
    ex = body.get("exercise") or {}
    ex_name = (ex.get("exercise") or ex.get("name") or "").strip()[:200]
    raw_text = (body.get("text") or "").strip()[:500]
    if not ex_name:
        return _err("bad_exercise")
    if len(raw_text) < 1:
        return _err("bad_text")

    def _check():
        cur = db.execute(
            "SELECT id FROM ai_workout_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id))
        return bool(cur.fetchone())

    if not await run_db(_check):
        return _err("bad_session", 404)
    result = await run_in_thread(gemini_parse_exercise_result, ex, raw_text)

    def _log():
        db.execute(
            "INSERT INTO ai_exercise_logs"
            " (session_id, user_id, exercise_name, planned_json, raw_input, result_json, status)"
            " VALUES (?, ?, ?, ?, ?, ?, 'done')",
            (session_id, user_id, ex_name, _json.dumps(ex, ensure_ascii=False),
             raw_text, _json.dumps(result, ensure_ascii=False)))
        db.commit()
        return result

    saved = await run_db(_log)
    return web.json_response({"ok": True, "data": {"result": saved}})


@require_user
async def api_workout_review(request: web.Request):
    """Monthly AI review: propose exercise swaps, or {no_changes_needed: true}."""
    from trackcheck.database.connection import db
    from trackcheck.database.repositories import get_ai_plan, get_session_exercise_logs
    from trackcheck.utils.concurrency import run_in_thread
    from trackcheck.services.ai_service import gemini_monthly_review
    import json as _json
    user_id = request["tg_user"]["id"]

    def _load():
        plan_data = get_ai_plan(user_id)
        if not plan_data:
            return None
        cur = db.execute(
            "SELECT id, date, session_key, plan_json FROM ai_workout_sessions"
            " WHERE user_id = ? AND status = 'done' ORDER BY date DESC LIMIT 10",
            (user_id,))
        sessions = []
        for row in cur.fetchall():
            sid = row[0]
            sessions.append({
                "date": row[1], "session_key": row[2],
                "plan": _json.loads(row[3]),
                "logs": [{"exercise": l["exercise_name"], "result": l.get("result"),
                          "status": l["status"]}
                         for l in get_session_exercise_logs(sid)],
            })
        return plan_data, sessions

    loaded = await run_db(_load)
    if not loaded:
        return _err("bad_plan", 404)
    plan_data, sessions = loaded
    review = await run_in_thread(gemini_monthly_review, plan_data["plan"], sessions)
    if review is None:
        return _err("ai_failed", 502)
    return web.json_response({"ok": True, "data": review})


@require_user
async def api_workout_apply_review(request: web.Request):
    """Apply accepted monthly-review swaps: {accepted: [{day, week, old_exercise, new_exercise}]}."""
    from trackcheck.database.repositories import get_ai_plan, update_plan_json
    user_id = request["tg_user"]["id"]
    try:
        body = await request.json()
    except Exception:
        return _err("bad_json")
    accepted = body.get("accepted")
    if not isinstance(accepted, list) or not accepted:
        return _err("bad_params")

    def _apply():
        plan_data = get_ai_plan(user_id)
        if not plan_data:
            return None
        plan = plan_data["plan"]
        applied = 0
        for ch in accepted:
            if not isinstance(ch, dict):
                continue
            week, day = ch.get("week"), ch.get("day")
            old, new = ch.get("old_exercise"), ch.get("new_exercise")
            if not all(isinstance(x, str) for x in (week, day, old, new)):
                continue
            lst = (plan.get(week) or {}).get(day)
            if not isinstance(lst, list):
                continue
            for ex in lst:
                nm = ex.get("exercise", ex.get("name"))
                if nm == old:
                    ex["exercise"] = new
                    if "name" in ex:
                        ex["name"] = new
                    applied += 1
                    break
        if applied:
            update_plan_json(user_id, plan)
        return {"applied": applied}

    result = await run_db(_apply)
    if result is None:
        return _err("bad_plan", 404)
    return web.json_response({"ok": True, "data": result})


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
    app.router.add_post("/api/diet/photo", api_diet_photo)
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
    return app
