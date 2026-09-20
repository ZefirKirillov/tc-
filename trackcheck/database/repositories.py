import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from trackcheck.database.connection import db
from trackcheck.config import (SPARK_FOR_CATEGORIES, SPARK_FOR_WORKOUT,
                               WEEKDAY_KEY, WEEKDAY_RU, MAX_SPARKS_PER_DAY)
from trackcheck.utils.dates import (user_today_str, user_now, user_today_date,
                                    user_weekday)
from trackcheck.services.gamification_service import get_current_rank


def save_user_settings(user_id: int, username: str, first_name: str):
    # NOTE: last_active_date is intentionally NOT set/overwritten here.
    # It's owned by update_streak()/get_streak() below - if we stamp it with
    # today's date on every call (which used to happen right before
    # update_streak() ran), update_streak() would always see last_date ==
    # today already and could never tell "a new day has started", so the
    # streak would never increment.
    db.execute('''
        INSERT INTO user_settings (user_id, username, first_name, last_active_date)
        VALUES (?, ?, ?, NULL)
        ON CONFLICT(user_id) DO UPDATE SET 
            username = excluded.username,
            first_name = excluded.first_name
    ''', (user_id, username, first_name))
    db.commit()
    _name_cache[user_id] = first_name



_name_cache: Dict[int, str] = {}



def get_user_name(user_id: int, fallback: Optional[str] = None) -> str:
    cached = _name_cache.get(user_id)
    if cached:
        return cached
    cursor = db.execute('SELECT first_name FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        _name_cache[user_id] = row[0]
        return row[0]
    return fallback or "друг"



def update_streak(user_id: int):
    today = user_today_str(user_id)
    yesterday = (user_now(user_id) - timedelta(days=1)).strftime('%Y-%m-%d')
    cursor = db.execute('SELECT streak_days, last_active_date FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        streak, last_date = row
        if last_date == yesterday:
            streak += 1
        elif last_date != today:
            streak = 1
        db.execute('''
            UPDATE user_settings SET streak_days = ?, last_active_date = ?
            WHERE user_id = ?
        ''', (streak, today, user_id))
        db.commit()



def get_streak(user_id: int) -> int:
    today = user_today_str(user_id)
    yesterday = (user_now(user_id) - timedelta(days=1)).strftime('%Y-%m-%d')
    cursor = db.execute('SELECT streak_days, last_active_date FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        return 0
    streak, last_date = row
    # Если последняя активность не сегодня и не вчера — стрик сброшен
    if last_date not in (today, yesterday):
        if last_date is not None:
            db.execute('UPDATE user_settings SET streak_days = 0 WHERE user_id = ?', (user_id,))
            db.commit()
        return 0
    return streak if streak else 0



def save_rating(user_id: int, category: str, rating: int, date: str):
    db.execute('''
        INSERT INTO ratings (user_id, category, rating, day_date)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, category, day_date) 
        DO UPDATE SET rating = excluded.rating
    ''', (user_id, category, rating, date))
    db.commit()



def get_ratings(user_id: int, days: int = 1) -> list:
    date_from = (user_now(user_id) - timedelta(days=days-1)).strftime('%Y-%m-%d')
    valid_categories = ('сон', 'еда', 'активность', 'зависание', 'настрой')
    cursor = db.execute('''
        SELECT category, AVG(rating) as avg_rating, COUNT(*) as count
        FROM ratings 
        WHERE user_id = ? AND day_date >= ? AND category IN {} 
        GROUP BY category
    '''.format(valid_categories), (user_id, date_from))
    return cursor.fetchall()



def get_daily_ratings(user_id: int, days: int = 7) -> list:
    date_from = (user_now(user_id) - timedelta(days=days-1)).strftime('%Y-%m-%d')
    valid_categories = ('сон', 'еда', 'активность', 'зависание', 'настрой')
    cursor = db.execute('''
        SELECT day_date, category, rating
        FROM ratings 
        WHERE user_id = ? AND day_date >= ? AND category IN {}
        ORDER BY day_date, category
    '''.format(valid_categories), (user_id, date_from))
    return cursor.fetchall()



def get_today_ratings(user_id: int) -> dict:
    today = user_today_str(user_id)
    cursor = db.execute('''
        SELECT category, rating FROM ratings 
        WHERE user_id = ? AND day_date = ?
    ''', (user_id, today))
    return {r[0]: r[1] for r in cursor.fetchall()}



def get_yesterday_ratings(user_id: int) -> dict:
    yesterday = (user_now(user_id) - timedelta(days=1)).strftime('%Y-%m-%d')
    cursor = db.execute('''
        SELECT category, rating FROM ratings 
        WHERE user_id = ? AND day_date = ?
    ''', (user_id, yesterday))
    return {r[0]: r[1] for r in cursor.fetchall()}



def _fetch_rank_data(user_id: int) -> dict:
    cursor = db.execute('SELECT * FROM user_ranks WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    today = user_today_str(user_id)
    if row:
        user_id, total_sparks, current_rank, last_spark_date, sparks_today, cat_completed, workout_completed = row
        if last_spark_date != today:
            sparks_today = 0
            cat_completed = 0
            workout_completed = 0
            db.execute('''
                UPDATE user_ranks 
                SET sparks_today = 0, categories_completed_today = 0, workout_completed_today = 0, last_spark_date = ?
                WHERE user_id = ?
            ''', (today, user_id))
            db.commit()
        actual_rank = get_current_rank(total_sparks)
        if actual_rank != current_rank:
            current_rank = actual_rank
            db.execute('UPDATE user_ranks SET current_rank = ? WHERE user_id = ?', (current_rank, user_id))
            db.commit()
        return {
            'user_id': user_id,
            'total_sparks': total_sparks,
            'current_rank': current_rank,
            'sparks_today': sparks_today,
            'categories_completed_today': cat_completed,
            'workout_completed_today': workout_completed
        }
    else:
        db.execute('''
            INSERT INTO user_ranks (user_id, total_sparks, current_rank, last_spark_date, sparks_today, categories_completed_today, workout_completed_today)
            VALUES (?, 0, 1, ?, 0, 0, 0)
        ''', (user_id, today))
        db.commit()
        return {
            'user_id': user_id,
            'total_sparks': 0,
            'current_rank': 1,
            'sparks_today': 0,
            'categories_completed_today': 0,
            'workout_completed_today': 0
        }



def get_or_create_rank_data(user_id: int) -> dict:
    return _fetch_rank_data(user_id)



def check_all_categories_completed(user_id: int) -> bool:
    today_ratings = get_today_ratings(user_id)
    required_categories = {'сон', 'еда', 'активность', 'зависание', 'настрой'}
    return required_categories.issubset(set(today_ratings.keys()))



def manual_categories_completed(user_id: int) -> bool:
    """'еда' и 'активность' теперь выставляются автоматически (после лога еды/тренировки
    или в конце дня), а не кнопками. Эта проверка - только по трём категориям, которые
    пользователь реально заполняет сам, чтобы не зацикливать его в меню рефлексии,
    ожидая недостижимых вручную оценок."""
    today_ratings = get_today_ratings(user_id)
    required_categories = {'сон', 'зависание', 'настрой'}
    return required_categories.issubset(set(today_ratings.keys()))



def _deduct_spark_for_skip(user_id: int):
    """Отнимает 1 искру за пропущенный тренировочный день."""
    cursor = db.execute('SELECT total_sparks, current_rank FROM user_ranks WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        return
    total = row[0]
    new_total = max(0, total - 1)
    new_rank = get_current_rank(new_total)
    db.execute('UPDATE user_ranks SET total_sparks = ?, current_rank = ? WHERE user_id = ?',
               (new_total, new_rank, user_id))
    db.commit()



def add_spark(user_id: int, spark_type: str) -> Tuple[bool, int, bool, int, int]:
    data = get_or_create_rank_data(user_id)
    # bonus_high bypasses daily limit
    if spark_type != 'bonus_high' and data['sparks_today'] >= MAX_SPARKS_PER_DAY:
        return (False, data['sparks_today'], False, data['current_rank'], data['current_rank'])
    if spark_type == 'categories' and data['categories_completed_today']:
        return (False, data['sparks_today'], False, data['current_rank'], data['current_rank'])
    if spark_type == 'workout' and data['workout_completed_today']:
        return (False, data['sparks_today'], False, data['current_rank'], data['current_rank'])
    old_rank = data['current_rank']
    today = user_today_str(user_id)
    if spark_type == 'categories':
        db.execute('''
            UPDATE user_ranks 
            SET total_sparks = total_sparks + ?, sparks_today = sparks_today + ?, 
                categories_completed_today = 1, last_spark_date = ?
            WHERE user_id = ?
        ''', (SPARK_FOR_CATEGORIES, SPARK_FOR_CATEGORIES, today, user_id))
    else:
        db.execute('''
            UPDATE user_ranks 
            SET total_sparks = total_sparks + ?, sparks_today = sparks_today + ?, 
                workout_completed_today = 1, last_spark_date = ?
            WHERE user_id = ?
        ''', (SPARK_FOR_WORKOUT, SPARK_FOR_WORKOUT, today, user_id))
    db.commit()
    new_data = get_or_create_rank_data(user_id)
    new_rank = new_data['current_rank']
    rank_up = new_rank > old_rank
    return (True, new_data['sparks_today'], rank_up, old_rank, new_rank)



def get_or_create_workout_data(user_id: int) -> dict:
    cursor = db.execute('SELECT * FROM workouts WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    today = user_today_str(user_id)
    current_month = user_today_str(user_id, '%Y-%m')
    if row:
        user_id, goal, count, last_date, today_count = row
        if last_date:
            last_month = last_date[:7]
            if last_month != current_month:
                count = 0
                today_count = 0
                db.execute('''
                    UPDATE workouts 
                    SET current_count = 0, today_count = 0, last_workout_date = ?
                    WHERE user_id = ?
                ''', (today, user_id))
                db.commit()
        if last_date != today:
            today_count = 0
            db.execute('UPDATE workouts SET today_count = 0 WHERE user_id = ?', (user_id,))
            db.commit()
        return {
            'user_id': user_id,
            'monthly_goal': goal,
            'current_count': count,
            'last_workout_date': last_date,
            'today_count': today_count
        }
    else:
        db.execute('''
            INSERT INTO workouts (user_id, monthly_goal, current_count, last_workout_date, today_count)
            VALUES (?, 0, 0, ?, 0)
        ''', (user_id, today))
        db.commit()
        return {
            'user_id': user_id,
            'monthly_goal': 0,
            'current_count': 0,
            'last_workout_date': today,
            'today_count': 0
        }



def set_workout_goal(user_id: int, goal: int):
    db.execute('''
        INSERT INTO workouts (user_id, monthly_goal, current_count, last_workout_date, today_count)
        VALUES (?, ?, 0, ?, 0)
        ON CONFLICT(user_id) DO UPDATE SET monthly_goal = excluded.monthly_goal
    ''', (user_id, goal, user_today_str(user_id)))
    db.commit()



def add_workout(user_id: int) -> dict:
    today = user_today_str(user_id)
    db.execute('''
        UPDATE workouts 
        SET current_count = current_count + 1, today_count = today_count + 1, last_workout_date = ?
        WHERE user_id = ?
    ''', (today, user_id))
    db.commit()
    return get_or_create_workout_data(user_id)



def change_workout_goal(user_id: int, new_goal: int):
    db.execute('UPDATE workouts SET monthly_goal = ? WHERE user_id = ?', (new_goal, user_id))
    db.commit()



def save_diet_profile(user_id: int, weight: float, height: float, age: int, gender: str,
                      activity_level: float, goal_type: str, target_weight_change: float,
                      target_days: int, daily_calories: float):
    today = user_today_str(user_id)
    db.execute('''
        INSERT INTO diet_profile (user_id, weight, height, age, gender, activity_level,
                                   goal_type, target_weight_change, target_days, daily_calories, last_update_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            weight = excluded.weight,
            height = excluded.height,
            age = excluded.age,
            gender = excluded.gender,
            activity_level = excluded.activity_level,
            goal_type = excluded.goal_type,
            target_weight_change = excluded.target_weight_change,
            target_days = excluded.target_days,
            daily_calories = excluded.daily_calories,
            last_update_date = excluded.last_update_date
    ''', (user_id, weight, height, age, gender, activity_level, goal_type,
          target_weight_change, target_days, daily_calories, today))
    db.commit()



def get_diet_profile(user_id: int) -> Optional[dict]:
    cursor = db.execute('SELECT * FROM diet_profile WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        return dict(row)
    return None



def save_food_log(user_id: int, meal_type: str, description: str, calories: float):
    today = user_today_str(user_id)
    db.execute('''
        INSERT INTO diet_log (user_id, date, meal_type, food_description, calories)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, today, meal_type, description, calories))
    db.commit()



def get_today_calories(user_id: int) -> float:
    today = user_today_str(user_id)
    cursor = db.execute('SELECT SUM(calories) FROM diet_log WHERE user_id = ? AND date = ?', (user_id, today))
    row = cursor.fetchone()
    return row[0] if row[0] else 0.0



def get_today_food_log(user_id: int) -> list:
    today = user_today_str(user_id)
    cursor = db.execute('''
        SELECT meal_type, food_description, calories FROM diet_log
        WHERE user_id = ? AND date = ?
        ORDER BY timestamp
    ''', (user_id, today))
    return cursor.fetchall()



def save_weight_log(user_id: int, weight: float):
    today = user_today_str(user_id)
    db.execute('INSERT INTO weight_log (user_id, date, weight) VALUES (?, ?, ?)', (user_id, today, weight))
    db.commit()



def get_last_weight(user_id: int) -> Optional[float]:
    cursor = db.execute('SELECT weight FROM weight_log WHERE user_id = ? ORDER BY date DESC LIMIT 1', (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None



def save_body_fat(user_id: int, body_fat: float):
    today = user_today_str(user_id)
    db.execute('INSERT INTO body_fat_log (user_id, date, body_fat) VALUES (?, ?, ?)', (user_id, today, body_fat))
    db.commit()



def add_my_food(user_id: int, name: str, calories: float):
    try:
        db.execute('INSERT INTO my_foods (user_id, name, calories) VALUES (?, ?, ?)', (user_id, name, calories))
        db.commit()
    except sqlite3.IntegrityError:
        pass



def get_my_foods(user_id: int) -> List[Tuple[str, float]]:
    cursor = db.execute('SELECT name, calories FROM my_foods WHERE user_id = ? ORDER BY name', (user_id,))
    return cursor.fetchall()



def save_last_ai_answer(user_id: int, answer: str):
    db.execute('UPDATE user_settings SET last_ai_answer = ? WHERE user_id = ?', (answer, user_id))
    db.commit()



def get_last_ai_answer(user_id: int) -> Optional[str]:
    cursor = db.execute('SELECT last_ai_answer FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None



def calculate_bmr(weight: float, height: float, age: int, gender: str) -> float:
    if gender == 'мужской':
        return 10 * weight + 6.25 * height - 5 * age + 5
    else:
        return 10 * weight + 6.25 * height - 5 * age - 161



def calculate_tdee(bmr: float, activity_level: float) -> float:
    return bmr * activity_level



def calculate_daily_calories(tdee: float, goal_type: str, target_weight_change: float, target_days: int, gender: str) -> Tuple[float, str]:
    if goal_type == 'maintain':
        return tdee, "ok"
    total_energy = abs(target_weight_change) * 7700
    daily_adjustment = total_energy / target_days
    max_adjustment = 1000
    warning = "ok"
    if daily_adjustment > max_adjustment:
        daily_adjustment = max_adjustment
        warning = f"⚠️ Цель слишком амбициозна. Дефицит ограничен {max_adjustment} ккал/день. Для достижения цели потребуется больше времени."
    if goal_type == 'loss':
        calories = tdee - daily_adjustment
    else:
        calories = tdee + daily_adjustment
    min_calories = 1200 if gender == 'женский' else 1500
    if calories < min_calories:
        calories = min_calories
        warning = f"⚠️ Рассчитанная норма слишком низкая. Установлен безопасный минимум {min_calories} ккал/день. Рекомендуется пересмотреть цель."
    return calories, warning



def get_tasks_for_today(user_id: int) -> list:
    today = user_today_str(user_id)
    today_wd = str(user_weekday(user_id))
    cursor = db.execute("""
        SELECT id, title, is_priority, deadline, repeat_days, is_done, done_date
        FROM tasks WHERE user_id = ?
    """, (user_id,))
    rows = cursor.fetchall()
    result = []
    for row in rows:
        task_id, title, is_priority, deadline, repeat_days, is_done, done_date = row
        if repeat_days:
            # Повторяющаяся: показываем если сегодня нужный день и не выполнена сегодня
            days = repeat_days.split(',')
            if today_wd not in days:
                continue
            if done_date == today:
                continue
        else:
            # Разовая: пропускаем если уже выполнена
            if is_done:
                continue
        result.append({
            'id': task_id, 'title': title, 'is_priority': bool(is_priority),
            'deadline': deadline, 'repeat_days': repeat_days,
            'is_done': bool(is_done), 'done_date': done_date
        })
    return result



def get_all_active_tasks(user_id: int) -> list:
    today = user_today_str(user_id)
    today_wd = str(user_weekday(user_id))
    cursor = db.execute("""
        SELECT id, title, is_priority, deadline, repeat_days, is_done, done_date
        FROM tasks WHERE user_id = ? ORDER BY is_priority DESC, deadline ASC NULLS LAST, id ASC
    """, (user_id,))
    rows = cursor.fetchall()
    result = []
    for row in rows:
        task_id, title, is_priority, deadline, repeat_days, is_done, done_date = row
        if repeat_days:
            days = repeat_days.split(',')
            done_today = (done_date == today)
            result.append({
                'id': task_id, 'title': title, 'is_priority': bool(is_priority),
                'deadline': deadline, 'repeat_days': repeat_days,
                'is_done': done_today, 'done_date': done_date
            })
        else:
            if is_done:
                continue
            result.append({
                'id': task_id, 'title': title, 'is_priority': bool(is_priority),
                'deadline': deadline, 'repeat_days': repeat_days,
                'is_done': False, 'done_date': done_date
            })
    return result



def get_urgent_tasks_for_menu(user_id: int) -> list:
    """Задачи для главного меню: приоритетные + дедлайн <= 3 дней."""
    today = user_today_date(user_id)
    tasks = get_tasks_for_today(user_id)
    urgent = []
    for t in tasks:
        days_left = None
        if t['deadline']:
            try:
                dl = datetime.strptime(t['deadline'], '%Y-%m-%d').date()
                days_left = (dl - today).days
            except:
                pass
        show = t['is_priority'] or (days_left is not None and days_left <= 3)
        if show:
            t['days_left'] = days_left
            urgent.append(t)
    return urgent[:5]



def complete_task(task_id: int, user_id: int):
    today = user_today_str(user_id)
    cursor = db.execute('SELECT repeat_days FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id))
    row = cursor.fetchone()
    if not row:
        return
    repeat_days = row[0]
    if repeat_days:
        db.execute('UPDATE tasks SET done_date = ? WHERE id = ? AND user_id = ?', (today, task_id, user_id))
    else:
        db.execute('UPDATE tasks SET is_done = 1, done_date = ? WHERE id = ? AND user_id = ?', (today, task_id, user_id))
    db.commit()



def delete_task(task_id: int, user_id: int):
    db.execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id))
    db.commit()



def add_task(user_id: int, title: str, is_priority: bool, deadline: Optional[str], repeat_days: Optional[str]):
    db.execute("""
        INSERT INTO tasks (user_id, title, is_priority, deadline, repeat_days)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, title, int(is_priority), deadline, repeat_days))
    db.commit()



def get_ai_plan(user_id: int) -> Optional[dict]:
    cursor = db.execute("SELECT * FROM ai_workout_plan WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return None
    plan = dict(row)
    plan["plan"] = json.loads(plan["plan_json"])
    return plan



def save_ai_plan(user_id: int, mode: str, goal: str, level: str,
                 days_per_week: int, plan: dict, cycle_weeks: int = 1):
    today = user_today_str(user_id)
    plan_json = json.dumps(plan, ensure_ascii=False)
    db.execute("""
        INSERT INTO ai_workout_plan (user_id, mode, goal, level, days_per_week, plan_json, cycle_weeks, start_date, last_monthly_review)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            mode=excluded.mode, goal=excluded.goal, level=excluded.level,
            days_per_week=excluded.days_per_week, plan_json=excluded.plan_json,
            cycle_weeks=excluded.cycle_weeks,
            start_date=CASE WHEN ai_workout_plan.start_date IS NULL THEN excluded.start_date ELSE ai_workout_plan.start_date END
    """, (user_id, mode, goal, level, days_per_week, plan_json, cycle_weeks, today, today))
    db.commit()



def delete_all_workout_data(user_id: int):
    """Сбрасывает все данные тренировок пользователя."""
    db.execute("DELETE FROM ai_workout_plan WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM ai_workout_sessions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM ai_exercise_logs WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM workout_log WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM exercises WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM exercise_categories WHERE user_id = ?", (user_id,))
    db.execute("UPDATE workouts SET current_count=0, today_count=0, last_workout_date=NULL WHERE user_id = ?", (user_id,))
    db.commit()



def get_current_week_session_key(plan_data: dict, start_date: str, user_id: Optional[int] = None) -> str:
    """Определяет какую неделю цикла использовать сегодня."""
    now_date = user_today_date(user_id) if user_id is not None else datetime.now().date()
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
    except Exception:
        start = now_date
    today = now_date
    weeks_passed = max(0, (today - start).days // 7)
    # cycle_weeks может быть в plan_data или в вложенном plan
    plan = plan_data.get("plan", plan_data)
    cycle_weeks = plan_data.get("cycle_weeks", plan.get("cycle_weeks", 1)) or 1
    week_idx = (weeks_passed % cycle_weeks) + 1
    return f"week_{week_idx}"



def get_today_plan(plan_data: dict, user_id: Optional[int] = None) -> Optional[list]:
    """Возвращает список упражнений на сегодня (по времени пользователя) или None если день отдыха."""
    if not plan_data:
        return None
    plan = plan_data.get("plan")
    if not plan:
        return None
    now = user_now(user_id) if user_id is not None else datetime.now()
    start_date = plan_data.get("start_date") or now.strftime("%Y-%m-%d")
    week_key = get_current_week_session_key(plan_data, start_date, user_id)
    today_key = WEEKDAY_KEY[now.weekday()]
    week = plan.get(week_key) or plan.get("week_1") or {}
    exercises = week.get(today_key)
    if not exercises:
        return None
    if not isinstance(exercises, list) or len(exercises) == 0:
        return None
    return exercises



def get_today_session(user_id: int) -> Optional[dict]:
    today = user_today_str(user_id)
    cursor = db.execute(
        "SELECT * FROM ai_workout_sessions WHERE user_id = ? AND date = ?",
        (user_id, today)
    )
    row = cursor.fetchone()
    if not row:
        return None
    s = dict(row)
    s["plan"] = json.loads(s["plan_json"])
    return s



def create_today_session(user_id: int, plan_data: dict) -> Optional[dict]:
    """Создаёт сессию на сегодня если её нет."""
    existing = get_today_session(user_id)
    if existing:
        return existing
    today_exercises = get_today_plan(plan_data, user_id)
    if not today_exercises:
        return None
    today = user_today_str(user_id)
    weekday = user_weekday(user_id)
    start_date = plan_data.get("start_date") or today
    week_key = get_current_week_session_key(plan_data, start_date, user_id)
    today_key = WEEKDAY_KEY[weekday]
    session_key = f"{week_key}_{today_key}"
    plan_json = json.dumps(today_exercises, ensure_ascii=False)
    try:
        db.execute("""
            INSERT INTO ai_workout_sessions (user_id, date, weekday, session_key, plan_json, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (user_id, today, weekday, session_key, plan_json))
        db.commit()
    except Exception as e:
        print(f"[SESSION] Insert error: {e}")
    return get_today_session(user_id)



def get_session_exercise_logs(session_id: int) -> list:
    cursor = db.execute(
        "SELECT * FROM ai_exercise_logs WHERE session_id = ? ORDER BY id",
        (session_id,)
    )
    rows = cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("planned_json"):
            d["planned"] = json.loads(d["planned_json"])
        if d.get("result_json"):
            d["result"] = json.loads(d["result_json"])
        result.append(d)
    return result



def get_previous_same_session(user_id: int, session_key: str, exclude_date: str) -> Optional[dict]:
    """Возвращает предыдущую сессию того же типа (прошлая неделя, месяц назад, первая)."""
    cursor = db.execute("""
        SELECT * FROM ai_workout_sessions
        WHERE user_id = ? AND session_key LIKE ? AND date != ? AND status = 'done'
        ORDER BY date DESC LIMIT 3
    """, (user_id, f"%{session_key.split('_', 2)[-1]}", exclude_date))
    rows = cursor.fetchall()
    if not rows:
        return None
    sessions = []
    for row in rows:
        s = dict(row)
        s["plan"] = json.loads(s["plan_json"])
        s["logs"] = get_session_exercise_logs(s["id"])
        sessions.append(s)
    return sessions



def update_plan_json(user_id: int, new_plan: dict):
    plan_json = json.dumps(new_plan, ensure_ascii=False)
    db.execute("UPDATE ai_workout_plan SET plan_json = ? WHERE user_id = ?",
               (plan_json, user_id))
    db.commit()



def update_session_exercise_plan(user_id: int, session_id: int,
                                  session_key: str, new_exercises: list):
    """Обновляет план упражнений в текущей и будущей сессии."""
    plan_json = json.dumps(new_exercises, ensure_ascii=False)
    db.execute("UPDATE ai_workout_sessions SET plan_json = ? WHERE id = ?",
               (plan_json, session_id))
    # Обновляем и в основном плане для будущих сессий
    plan_data = get_ai_plan(user_id)
    if plan_data:
        plan = plan_data["plan"]
        parts = session_key.split("_", 2)  # week_1_monday
        if len(parts) >= 3:
            week_key = f"{parts[0]}_{parts[1]}"
            day_key = parts[2]
            if week_key in plan and day_key in plan[week_key]:
                plan[week_key][day_key] = new_exercises
                update_plan_json(user_id, plan)
    db.commit()



def get_next_training_day(plan_data: dict, user_id: Optional[int] = None) -> Optional[str]:
    """Возвращает дату и название следующей тренировки."""
    plan = plan_data["plan"]
    start_date = plan_data["start_date"]
    today = user_today_date(user_id) if user_id is not None else datetime.now().date()
    today_weekday = today.weekday()

    for offset in range(1, 8):
        check_date = today + timedelta(days=offset)
        check_weekday = check_date.weekday()
        check_wd_key = WEEKDAY_KEY[check_weekday]
        weeks_passed = (check_date - datetime.strptime(start_date, "%Y-%m-%d").date()).days // 7
        cycle_weeks = plan_data.get("cycle_weeks", 1)
        week_idx = (weeks_passed % cycle_weeks) + 1
        week_key = f"week_{week_idx}"
        week = plan.get(week_key, plan.get("week_1", {}))
        if week.get(check_wd_key):
            return check_date.strftime("%d.%m"), WEEKDAY_RU[check_weekday]
    return None, None



def get_weekly_workout_progress(user_id: int) -> tuple:
    """Возвращает (выполнено, план) тренировок за текущую неделю."""
    plan_data = get_ai_plan(user_id)
    days_per_week = plan_data['days_per_week'] if plan_data else 0
    # Считаем начало недели (понедельник)
    today = user_today_date(user_id)
    week_start = today - timedelta(days=today.weekday())
    week_start_str = week_start.strftime('%Y-%m-%d')
    cursor = db.execute(
        "SELECT COUNT(*) FROM ai_workout_sessions WHERE user_id = ? AND date >= ? AND status = 'done'",
        (user_id, week_start_str)
    )
    row = cursor.fetchone()
    done = row[0] if row else 0
    return done, days_per_week
