"""Автоматические оценки «еда» и «активность» — по правилам, без ИИ.

Еда: насколько съеденное близко к дневной цели по калориям.
  - в течение дня — сравнение с ожидаемым к этому часу (кривая приёмов пищи);
  - в 23:55 — итог относительно полной дневной цели;
  - ничего не съедено за день (или цель не задана, а значит дневник недоступен) → 1.
Активность: насколько хорошо выполнена тренировка по плану.
  - каждое упражнение плана → 0..1 (пропуск = 0; выполнено — сравнение подходов,
    повторов и веса с планом, каждое ≤ 100%); итог — среднее → шкала 1..10;
  - пропущен день / тренировка не сделана / плана нет → 1; день отдыха → 5
    (ставится сразу в начале дня, а не в 23:55).
Вручную эти две категории не ставятся. Когда заполнены все 5 — начисляется искра.
"""
import re
from typing import Optional

from trackcheck.config import DEFAULT_TIMEZONE
from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    get_diet_profile, get_today_calories, get_today_session,
    get_session_exercise_logs, get_today_ratings, save_rating, get_ai_plan,
    get_today_plan, check_all_categories_completed, add_spark,
)
from trackcheck.utils.dates import user_now, user_today_str

AUTO_CATEGORIES = ("еда", "активность")

# Отклонение от цели (доля) → оценка. Первое подходящее значение.
_DEVIATION_SCALE = [
    (0.05, 10), (0.10, 9), (0.15, 8), (0.20, 7), (0.25, 6),
    (0.30, 5), (0.40, 4), (0.50, 3), (0.65, 2),
]

# Какая доля дневных калорий обычно съедена к этому часу (линейно между точками).
_EATING_CURVE = [(0, 0.0), (6, 0.0), (9, 0.25), (13, 0.55), (19, 0.85), (22, 1.0), (24, 1.0)]


def _score_from_deviation(dev: float) -> int:
    dev = round(dev, 6)  # 2200/2000-1 = 0.10000000000000009 must still count as 10%
    for limit, score in _DEVIATION_SCALE:
        if dev <= limit:
            return score
    return 1


def _expected_fraction(hour_float: float) -> float:
    for (h0, f0), (h1, f1) in zip(_EATING_CURVE, _EATING_CURVE[1:]):
        if h0 <= hour_float <= h1:
            return f0 + (f1 - f0) * (hour_float - h0) / (h1 - h0)
    return 1.0


def diet_score(eaten: float, goal: float, hour_float: Optional[float] = None) -> int:
    """Чистая функция. hour_float=None — итог дня; иначе — с поправкой на время суток."""
    if eaten <= 0 or goal <= 0:
        return 1
    if eaten > goal:  # перебор оцениваем всегда относительно полной цели
        return _score_from_deviation(eaten / goal - 1)
    target = goal if hour_float is None else goal * _expected_fraction(hour_float)
    if target <= 0 or eaten >= target:
        return 10 if hour_float is not None else _score_from_deviation(1 - eaten / goal)
    return _score_from_deviation(1 - eaten / target)


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _num(v) -> Optional[float]:
    """3 → 3; "6-8" → 6 (нижняя граница); "120кг" → 120; "собств. вес"/None/0 → None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    m = _NUM.search(str(v))
    if not m:
        return None
    x = float(m.group(0).replace(",", "."))
    return x if x > 0 else None


def exercise_score(planned: dict, log: Optional[dict]) -> float:
    """0..1 для одного упражнения плана."""
    if not log or log.get("status") != "done":
        return 0.0
    result = log.get("result") or {}
    parts = []
    for p_key, d_key in (("sets", "sets_done"), ("reps", "reps_done"), ("weight", "weight_done")):
        p, d = _num((planned or {}).get(p_key)), _num(result.get(d_key))
        if p is not None and d is not None:
            parts.append(min(1.0, d / p))
        elif p is not None and result.get(d_key) in (0, "0"):
            parts.append(0.0)
    return sum(parts) / len(parts) if parts else 1.0


def workout_score(planned: list, logs: list) -> int:
    """Чистая функция: среднее по упражнениям плана → 1..10."""
    def name(ex):
        return (ex.get("exercise") or ex.get("name") or "").strip()
    by_name = {}
    for l in logs:
        by_name.setdefault((l.get("exercise_name") or "").strip(), l)
    items = planned or [l.get("planned") or {"exercise": l.get("exercise_name")} for l in logs]
    if not items:
        return 1
    total = sum(exercise_score(ex, by_name.get(name(ex))) for ex in items) / len(items)
    return max(1, min(10, int(1 + 9 * total + 0.5)))  # half-up (round() is banker's: 6.5 → 6)


# --- DB-aware wrappers ---

def _hour_float(user_id: int) -> float:
    now = user_now(user_id)
    return now.hour + now.minute / 60


def compute_diet_rating(user_id: int, final: bool) -> Optional[int]:
    """None — пока рано оценивать (днём, когда ещё ничего не съедено)."""
    profile = get_diet_profile(user_id)
    goal = float(profile.get("daily_calories") or 0) if profile else 0.0
    eaten = float(get_today_calories(user_id) or 0)
    if not final and (goal <= 0 or eaten <= 0):
        return None
    return diet_score(eaten, goal, None if final else _hour_float(user_id))


def compute_activity_rating(user_id: int, final: bool) -> Optional[int]:
    plan_data = get_ai_plan(user_id)
    if not plan_data:
        return 1 if final else None
    session = get_today_session(user_id)
    if session and session.get("status") == "skipped":
        return 1
    today_plan = get_today_plan(plan_data, user_id)
    if not today_plan and not session:
        return 5  # день отдыха — оценка известна с утра
    if not session:
        return 1 if final else None  # тренировочный день, не начинал
    if session.get("status") != "done" and not final:
        return None
    planned = session.get("plan") if isinstance(session.get("plan"), list) else (today_plan or [])
    return workout_score(planned, get_session_exercise_logs(session["id"]))


def _save_auto(user_id: int, category: str, score: Optional[int]) -> bool:
    """Сохраняет оценку и, если теперь заполнены все 5 категорий, начисляет искру.
    Возвращает True, если искра начислена."""
    if score is None:
        return False
    save_rating(user_id, category, int(score), user_today_str(user_id))
    if check_all_categories_completed(user_id):
        ok, *_ = add_spark(user_id, "categories")
        return bool(ok)
    return False


def sync_diet_rating_for_today(user_id: int):
    """После каждой записи еды (бот и Mini App)."""
    _save_auto(user_id, "еда", compute_diet_rating(user_id, final=False))


def sync_activity_rating_for_today(user_id: int):
    """После завершения или пропуска тренировки (бот и Mini App)."""
    _save_auto(user_id, "активность", compute_activity_rating(user_id, final=False))


def ensure_rest_day_rating(user_id: int):
    """День отдыха → «активность» = 5 с начала дня. Только если оценки ещё нет —
    вызывается часто (открытие Mini App), уже выставленное не перезаписываем."""
    if "активность" in get_today_ratings(user_id):
        return
    plan_data = get_ai_plan(user_id)
    if not plan_data or get_today_session(user_id) or get_today_plan(plan_data, user_id):
        return
    _save_auto(user_id, "активность", 5)


async def start_daily_ratings_for_timezone(tz_name: str):
    """Планировщик, 00:01 по местному времени: день отдыха сразу получает 5."""
    from trackcheck.utils.concurrency import run_db
    await run_db(_start_daily_ratings_sync, tz_name)


def _start_daily_ratings_sync(tz_name: str):
    for user_id in _user_ids_for_timezone(tz_name):
        try:
            ensure_rest_day_rating(user_id)
        except Exception as e:
            print(f"[START RATINGS] user={user_id}: {e}")


def _user_ids_for_timezone(tz_name: str) -> list:
    if tz_name == DEFAULT_TIMEZONE:
        cursor = db.execute("SELECT user_id FROM user_settings WHERE timezone = ? OR timezone IS NULL", (tz_name,))
    else:
        cursor = db.execute("SELECT user_id FROM user_settings WHERE timezone = ?", (tz_name,))
    return [r[0] for r in cursor.fetchall()]



async def finalize_daily_ratings_for_timezone(tz_name: str):
    """Обёртка для планировщика: вся работа с БД — в пуле потоков, чтобы цикл
    по всем пользователям не блокировал event loop (бот и Mini App)."""
    from trackcheck.utils.concurrency import run_db
    await run_db(_finalize_daily_ratings_sync, tz_name)


def _finalize_daily_ratings_sync(tz_name: str):
    """Раз в сутки (23:55 по местному времени каждого часового пояса): итоговые
    оценки «еда» и «активность» за день по правилам выше (перезаписывают дневные)."""
    try:
        for user_id in _user_ids_for_timezone(tz_name):
            try:
                _save_auto(user_id, "еда", compute_diet_rating(user_id, final=True))
                _save_auto(user_id, "активность", compute_activity_rating(user_id, final=True))
            except Exception as e:
                print(f"[FINALIZE RATINGS] user={user_id}: {e}")
    except Exception as e:
        print(f"[FINALIZE RATINGS] Ошибка для {tz_name}: {e}")
