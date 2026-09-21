from trackcheck.config import DEFAULT_TIMEZONE
from trackcheck.database.connection import db
from trackcheck.database.repositories import (
    get_today_food_log, get_diet_profile, get_today_calories, get_today_session,
    get_session_exercise_logs, get_today_ratings, save_rating, get_ai_plan,
    get_today_plan,
)
from trackcheck.utils.dates import user_today_str
from trackcheck.services.ai_service import gemini_generate_rating


def sync_diet_rating_for_today(user_id: int):
    """Пересчитывает оценку категории 'еда' за сегодня на основе фактически
    залогированной еды. Вызывается после каждой новой записи о еде.
    Если ключ рейтингов (NARA_API / GOOGLE_API_KEY_RATINGS) не настроен - ничего не делает (не выдумывает оценку)."""
    food_log = get_today_food_log(user_id)
    if not food_log:
        return
    profile = get_diet_profile(user_id)
    goal = profile.get('daily_calories') if profile else None
    today_cal = get_today_calories(user_id)
    food_items = "; ".join(f"{meal}: {desc} ({int(cal)} ккал)" for meal, desc, cal in food_log)
    prompt = f"""Ты оцениваешь качество питания пользователя за сегодня по шкале от 1 до 10.
Дневная цель по калориям: {int(goal) if goal else 'не задана'} ккал.
Съедено сегодня: {int(today_cal)} ккал.
Приёмы пищи: {food_items}

10 — питание сбалансированное, разнообразное и укладывается в цель по калориям.
1 — питание явно вредное или сильно выходит за рамки цели.
Ответь СТРОГО в формате JSON без пояснений: {{"rating": <целое число 1-10>, "comment": "<одно короткое предложение по-русски>"}}"""
    result = gemini_generate_rating(prompt)
    if result:
        save_rating(user_id, 'еда', result['rating'], user_today_str(user_id))



def sync_activity_rating_for_today(user_id: int):
    """Пересчитывает оценку категории 'активность' за сегодня на основе фактически
    выполненной тренировки. Вызывается сразу после завершения тренировки."""
    session = get_today_session(user_id)
    if not session or session.get('status') != 'done':
        return
    logs = get_session_exercise_logs(session['id'])
    if logs:
        log_lines = []
        for log in logs:
            if log.get('status') == 'skipped':
                log_lines.append(f"{log['exercise_name']}: пропущено")
            else:
                result = log.get('result') or {}
                log_lines.append(f"{log['exercise_name']}: {result}")
        exercises_summary = "; ".join(log_lines)
    else:
        exercises_summary = "нет подробных данных, но сессия отмечена как выполненная"
    prompt = f"""Ты оцениваешь качество сегодняшней тренировки пользователя по шкале от 1 до 10
на основе того, что реально выполнено.
Упражнения: {exercises_summary}

10 — тренировка выполнена полностью и качественно.
Ниже — если многое пропущено, сделано не полностью или с явными трудностями.
Ответь СТРОГО в формате JSON без пояснений: {{"rating": <целое число 1-10>, "comment": "<одно короткое предложение по-русски>"}}"""
    result = gemini_generate_rating(prompt)
    if result:
        save_rating(user_id, 'активность', result['rating'], user_today_str(user_id))



async def finalize_daily_ratings_for_timezone(tz_name: str):
    """Раз в сутки (23:55 по местному времени каждого часового пояса): если 'еда' или
    'активность' за сегодня так и не были залогированы - проставляет 0, а для
    активности - 5, если по плану сегодня был день отдыха."""
    try:
        if tz_name == DEFAULT_TIMEZONE:
            cursor = db.execute("SELECT user_id FROM user_settings WHERE timezone = ? OR timezone IS NULL", (tz_name,))
        else:
            cursor = db.execute("SELECT user_id FROM user_settings WHERE timezone = ?", (tz_name,))
        user_ids = [r[0] for r in cursor.fetchall()]
        for user_id in user_ids:
            today = user_today_str(user_id)
            today_ratings = get_today_ratings(user_id)
            if 'еда' not in today_ratings:
                save_rating(user_id, 'еда', 0, today)
            if 'активность' not in today_ratings:
                plan_data = get_ai_plan(user_id)
                is_rest_day = bool(plan_data) and not get_today_plan(plan_data, user_id)
                save_rating(user_id, 'активность', 5 if is_rest_day else 0, today)
    except Exception as e:
        print(f"[FINALIZE RATINGS] Ошибка для {tz_name}: {e}")
