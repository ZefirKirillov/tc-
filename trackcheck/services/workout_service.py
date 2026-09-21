from datetime import datetime

from trackcheck.config import WEEKDAY_RU
from trackcheck.database.repositories import get_session_exercise_logs


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
            lines.append(f"{icon} {name}\n   План: {plan_str} → Факт: {done_str}")
        else:
            lines.append(f"{icon} {name} — {plan_str}")
    if session.get("feedback"):
        lines.append(f"\n💬 {session['feedback']}")
    return "\n".join(lines)
