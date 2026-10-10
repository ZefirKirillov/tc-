import copy
import re
from datetime import datetime

import json

from trackcheck.config import WEEKDAY_KEY, WEEKDAY_RU
from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    get_session_exercise_logs, get_ai_plan, update_plan_json,
    get_current_week_session_key, create_extra_session, add_workout, add_spark,
    update_streak, add_exercise_substitution, get_exercise_substitutions,
    set_substitution_weight,
)
from trackcheck.utils.dates import user_today_str


def format_plan_for_display(exercises: list, prev_logs: list = None) -> str:
    """Форматирует план упражнений для показа пользователю."""
    lines = []
    prev_map = {}
    if prev_logs:
        for log in prev_logs:
            if log.get("result"):
                prev_map[log["exercise_name"]] = log["result"]

    for i, ex in enumerate(exercises, 1):
        name = ex.get("exercise", ex.get("name", "?"))
        sets = ex.get("sets", "?")
        reps = ex.get("reps", "?")
        weight = ex.get("weight")
        line = f"{i}. {name}  {sets}×{reps}"
        if weight:
            line += f" @ {weight}кг"
        lines.append(line)

    text = "\n".join(lines)

    # Прошлый раз — только важное
    if prev_logs:
        important = []
        for log in prev_logs:
            if log["status"] == "skipped":
                important.append(f"⏭ {log['exercise_name']} — пропущено")
            elif log.get("result") and log["result"].get("note"):
                important.append(f"⚠️ {log['exercise_name']} — {log['result']['note']}")
        if important:
            text += "\n\nПрошлый раз:\n" + "\n".join(important)

    return text



def format_exercise_card(exercise: dict, index: int, total: int, prev_result: dict = None) -> str:
    """Форматирует карточку одного упражнения."""
    name = exercise.get("exercise", exercise.get("name", "?"))
    sets = exercise.get("sets", "?")
    reps = exercise.get("reps", "?")
    weight = exercise.get("weight")

    text = f"Упражнение {index} из {total}\n\n"
    text += f"{name}\n"
    text += f"Цель: {sets} подхода × {reps} повторений"
    if weight:
        text += f" @ {weight} кг"

    if prev_result:
        text += "\n\nПрошлый раз: "
        if prev_result.get("sets_done"):
            text += f"{prev_result['sets_done']}×{prev_result.get('reps_done','?')}"
        if prev_result.get("weight_done"):
            text += f" @ {prev_result['weight_done']} кг"
        if prev_result.get("note"):
            text += f" ({prev_result['note']})"

    text += "\n\nНапиши что сделал или нажми кнопку:"
    return text



def apply_monthly_changes(user_id: int, plan_data: dict, accepted_indices: list, changes: list) -> dict:
    """Применяет принятые изменения к плану."""
    import copy
    plan = copy.deepcopy(plan_data["plan"])
    for i in accepted_indices:
        if i >= len(changes):
            continue
        ch = changes[i]
        week = plan.get(ch["week"], {})
        day = week.get(ch["day"], [])
        for ex in day:
            if ex.get("exercise") == ch["old_exercise"]:
                ex["exercise"] = ch["new_exercise"]
    return plan



def _numbers(value) -> list:
    return [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", str(value))]



def goal_met(target: dict, result: dict) -> bool:
    """Выполнена ли весовая цель: подходы, повторения и вес не ниже плана.
    Повторения цели «8-10» считаются по верхней границе, а факт «10,10,8» —
    по худшему подходу. Без веса в цели — False (нечего поднимать)."""
    if not target.get("weight") or not result or result.get("completed") is False:
        return False
    t_sets, t_reps, t_weight = (_numbers(target.get("sets")), _numbers(target.get("reps")),
                                _numbers(target.get("weight")))
    d_sets, d_reps = _numbers(result.get("sets_done")), _numbers(result.get("reps_done"))
    # Вес не указан в ответе — значит работал с плановым
    d_weight = _numbers(result.get("weight_done")) or t_weight
    if not (t_sets and t_reps and t_weight and d_sets and d_reps and d_weight):
        return False
    if len(d_reps) > 1:
        d_reps_val = min(d_reps)
    else:
        d_reps_val = d_reps[0]
    return (d_sets[0] >= t_sets[0] and d_reps_val >= max(t_reps)
            and d_weight[0] >= t_weight[0])



def format_weight(w) -> str:
    return f"{float(w):g}"



def raise_exercise_weight(plan: dict, exercise_name: str, increment: float) -> dict:
    """Поднимает вес упражнения во всех неделях/днях плана, где оно есть с весом."""
    plan = copy.deepcopy(plan)
    target = exercise_name.strip().lower()
    for week_key, week in plan.items():
        if not week_key.startswith("week_") or not isinstance(week, dict):
            continue
        for day in week.values():
            if not isinstance(day, list):
                continue
            for ex in day:
                name = str(ex.get("exercise", ex.get("name", ""))).strip().lower()
                w = _numbers(ex.get("weight"))
                if name == target and w:
                    ex["weight"] = round(w[0] + increment, 2)
    return plan



def _format_full_plan(plan: dict, goal: str, level: str, days: int) -> str:
    print(f"[FORMAT_PLAN] Input: cycle_weeks={plan.get('cycle_weeks')}, keys={[k for k in plan.keys() if 'week' in k]}")
    lines = []
    if goal:
        lines.append(f"Твой план — {goal}, {level}\n")
    
    cycle = plan.get("cycle_weeks", 1)
    if not cycle or cycle < 1:
        print(f"[FORMAT_PLAN] WARNING: Invalid cycle_weeks={cycle}, defaulting to 1")
        cycle = 1
    
    for w in range(1, cycle + 1):
        week_key = f"week_{w}"
        week = plan.get(week_key, {})
        print(f"[FORMAT_PLAN] Week {w}: found={bool(week)}, days={list(week.keys()) if week else 'none'}")
        if not week:
            continue
        if cycle > 1:
            lines.append(f"Неделя {w}:")
        day_order = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        day_names = {"monday":"Пн","tuesday":"Вт","wednesday":"Ср","thursday":"Чт",
                     "friday":"Пт","saturday":"Сб","sunday":"Вс"}
        for day_key in day_order:
            exs = week.get(day_key)
            if not exs:
                continue
            lines.append(f"\n{day_names[day_key]}:")
            for ex in exs:
                name = ex.get("exercise", ex.get("name", "?"))
                sets = ex.get("sets","?")
                reps = ex.get("reps","?")
                weight = ex.get("weight")
                line = f"  {name}  {sets}×{reps}"
                if weight:
                    line += f" @ {weight}кг"
                lines.append(line)
    
    result = "\n".join(lines)
    if not result:
        print(f"[FORMAT_PLAN] WARNING: Empty result! Plan structure: {plan}")
    else:
        print(f"[FORMAT_PLAN] Output ({len(lines)} lines): {result[:200]}")
    return result



def _format_session_detail(session: dict) -> str:
    """Форматирует одну сессию с подробностями."""
    date_str = datetime.strptime(session["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
    wd = WEEKDAY_RU.get(session.get("weekday", 0), "")
    status = session.get("status", "")
    lines = [f"📅 {wd}, {date_str}"]
    if status == "skipped":
        reason = session.get("skip_reason") or ""
        lines.append(f"⏭ Пропуск" + (f" — {reason}" if reason else ""))
        return "\n".join(lines)
    logs = get_session_exercise_logs(session["id"])
    for log in logs:
        icon = "✅" if log["status"] == "done" else "⏭"
        name = log["exercise_name"]
        planned = log.get("planned") or {}
        res = log.get("result")
        plan_str = f"{planned.get('sets','?')}×{planned.get('reps','?')}"
        if planned.get("weight"):
            plan_str += f" @ {planned['weight']}кг"
        if res and isinstance(res, dict) and log["status"] == "done":
            s = res.get("sets_done","?")
            r = res.get("reps_done","?")
            w = res.get("weight_done")
            done_str = f"{s}×{r}" + (f" @ {w}кг" if w else "")
            if res.get("note") and not log.get("planned"):
                done_str += f" ({res['note']})"
            if res.get("replaced"):
                lines.append(f"🔄 {name} (вместо «{res['replaced']}»)\n   Факт: {done_str}")
            elif not log.get("planned"):
                # Запись текстом в день отдыха — плана нет
                lines.append(f"{icon} {name}\n   Факт: {done_str}")
            else:
                lines.append(f"{icon} {name}\n   План: {plan_str} → Факт: {done_str}")
        else:
            lines.append(f"{icon} {name} — {plan_str}")
    if session.get("feedback"):
        lines.append(f"\n💬 {session['feedback']}")
    return "\n".join(lines)



# ── Сессия тренировки: общая логика бота и Mini App ─────────────────────────

def exercise_name(ex: dict) -> str:
    return ex.get("exercise", ex.get("name", "?"))



def log_exercise(session_id: int, user_id: int, name: str, planned, result,
                 raw_input: str = None, status: str = "done"):
    db.execute("""
        INSERT INTO ai_exercise_logs
        (session_id, user_id, exercise_name, planned_json, raw_input, result_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, user_id, name,
          json.dumps(planned, ensure_ascii=False) if planned is not None else None,
          raw_input,
          json.dumps(result, ensure_ascii=False) if result is not None else None,
          status))
    db.commit()



def count_workout(user_id: int):
    """Засчитывает тренировку: счётчик, искра, стрик. Рейтинг активности
    вызывающий синкает сам (бот — в фоне, API — сразу).
    Возвращает (искра начислена, новый ранг?, ранг)."""
    add_workout(user_id)
    ok, _, rank_up, _, new_rank = add_spark(user_id, "workout")
    update_streak(user_id)
    return ok, rank_up, new_rank



def plan_raise_target(ex: dict, result: dict = None):
    """Цель с весом выполнена — предложим поднять вес в плане.
    Без result — нажата «Цель выполнена», проверять нечего."""
    if ex.get("weight") and (result is None or goal_met(ex, result)):
        return {"kind": "plan", "name": exercise_name(ex), "weight": ex.get("weight")}
    return None



def apply_weight_raise(user_id: int, target: dict, increment: float) -> float:
    """Поднимает вес: в плане (все вхождения упражнения) или в последней
    замене — тогда новый вес подскажется в следующий раз."""
    new_weight = round(float(target["weight"]) + increment, 2)
    if target["kind"] == "plan":
        plan_data = get_ai_plan(user_id)
        if plan_data:
            update_plan_json(user_id, raise_exercise_weight(plan_data["plan"], target["name"], increment))
    else:
        set_substitution_weight(user_id, int(target["sub_id"]), new_weight)
    return new_weight



def substitution_suggestions(user_id: int, original_name: str) -> list:
    out = []
    for sub in get_exercise_substitutions(user_id, original_name):
        out.append({"id": sub["id"], "name": sub["substitute_name"], "sets": sub.get("sets"),
                    "reps": sub.get("reps"), "weight": sub.get("weight")})
    return out



def log_substitution_repeat(user_id: int, session_id: int, ex: dict, sub: dict):
    """Повтор прошлой замены с теми же цифрами. Возвращает (result, raise_target)."""
    original = exercise_name(ex)
    result = {"sets_done": sub.get("sets"), "reps_done": sub.get("reps"),
              "weight_done": sub.get("weight"), "completed": True, "note": None,
              "replaced": original}
    log_exercise(session_id, user_id, sub["substitute_name"], ex, result)
    new_id = add_exercise_substitution(user_id, original, sub["substitute_name"],
                                       sub.get("sets"), sub.get("reps"), sub.get("weight"))
    raise_target = None
    if sub.get("weight"):
        raise_target = {"kind": "sub", "sub_id": new_id, "name": sub["substitute_name"],
                        "weight": sub["weight"]}
    return result, raise_target



def log_substitution_items(user_id: int, session_id: int, ex: dict, items: list, raw: str):
    """Замена, описанная текстом (уже разобранная ИИ). Цель для вопроса про вес —
    прошлые цифры этой же замены. Возвращает (results, raise_target)."""
    original = exercise_name(ex)
    previous = {s["substitute_name"].strip().lower(): s
                for s in get_exercise_substitutions(user_id, original, limit=100)}
    results, raise_target = [], None
    for it in items:
        result = {"sets_done": it.get("sets_done"), "reps_done": it.get("reps_done"),
                  "weight_done": it.get("weight_done"), "completed": True,
                  "note": it.get("note"), "replaced": original}
        log_exercise(session_id, user_id, it["exercise"], ex, result, raw_input=raw)
        new_id = add_exercise_substitution(user_id, original, it["exercise"], it.get("sets_done"),
                                           it.get("reps_done"), it.get("weight_done"))
        prev = previous.get(it["exercise"].strip().lower())
        if raise_target is None and prev and goal_met(
                {"sets": prev.get("sets"), "reps": prev.get("reps"), "weight": prev.get("weight")},
                result):
            raise_target = {"kind": "sub", "sub_id": new_id, "name": it["exercise"],
                            "weight": it.get("weight_done") or prev.get("weight")}
        results.append({"exercise_name": it["exercise"], "result": result})
    return results, raise_target



def current_plan_week(plan_data: dict, user_id: int):
    """(week_key, week) текущей недели цикла, как в get_today_plan."""
    plan = plan_data["plan"]
    start_date = plan_data.get("start_date") or user_today_str(user_id)
    week_key = get_current_week_session_key(plan_data, start_date, user_id)
    if not plan.get(week_key):
        week_key = "week_1"
    return week_key, plan.get(week_key) or {}



def plan_day_options(plan_data: dict, user_id: int) -> list:
    """Тренировочные дни текущей недели — для тренировки в день отдыха."""
    _, week = current_plan_week(plan_data, user_id)
    out = []
    for wd, key in WEEKDAY_KEY.items():
        exercises = week.get(key)
        if isinstance(exercises, list) and exercises:
            out.append({"key": key, "label": WEEKDAY_RU[wd],
                        "exercises": [exercise_name(ex) for ex in exercises]})
    return out



def start_plan_day(user_id: int, plan_data: dict, day_key: str):
    """Разовая тренировка дня из плана сегодня. Расписание не меняется; ключ
    сессии — ключ выбранного дня, чтобы «прошлый раз» считался вместе с ним.
    Возвращает (session, error) — error: "bad_day" | "session_exists"."""
    week_key, week = current_plan_week(plan_data, user_id)
    exercises = week.get(day_key)
    if not isinstance(exercises, list) or not exercises:
        return None, "bad_day"
    session = create_extra_session(user_id, f"{week_key}_{day_key}", exercises)
    return (session, None) if session else (None, "session_exists")



def save_free_workout(user_id: int, items: list, raw: str):
    """Тренировка, описанная текстом в день отдыха: сессия сразу выполнена.
    Возвращает (session, results) или (None, None) если сессия на сегодня уже есть."""
    plan = [{"exercise": it["exercise"], "sets": it.get("sets_done"),
             "reps": it.get("reps_done"), "weight": it.get("weight_done")} for it in items]
    session = create_extra_session(user_id, "free", plan, status="done")
    if not session:
        return None, None
    results = []
    for it in items:
        result = {"sets_done": it.get("sets_done"), "reps_done": it.get("reps_done"),
                  "weight_done": it.get("weight_done"), "completed": True,
                  "note": it.get("note")}
        log_exercise(session["id"], user_id, it["exercise"], None, result, raw_input=raw)
        results.append({"exercise_name": it["exercise"], "result": result})
    return session, results
