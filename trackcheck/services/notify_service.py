"""Персональные напоминания: AI-текст (Nara -> Google fallback) + шаблонный fallback.

Каденс (ответы пользователя):
- обычные: каждые 6 часов
- важные: каждый час. Важное = задача с 🔥 ИЛИ дедлайн сегодня/завтра
  ИЛИ (то же правило для тренировок/диеты: сегодня тренировка не сделана /
  калории сильно мимо цели = важное, иначе обычное).
- 24/7 без тихих часов.
- Один слот: новое уведомление удаляет предыдущее; любое взаимодействие
  пользователя с ботом удаляет последнее уведомление.
- Кнопки зависят от контента (задачи -> задачи, диета -> диета, ...).
- Mute-кнопка: молчание до 08:00 по времени пользователя.
- Тумблер вкл/выкл хранится в БД (переживает рестарт).
- Шлём всем у кого есть открытые задачи / незакрытый день, бессрочно.
"""
from datetime import datetime, timedelta
from typing import Optional

from trackcheck.database.connection import db
from trackcheck.utils.dates import get_user_timezone, user_now, user_today_date, user_today_str
from trackcheck.utils.action_log import log_action


# --- DB state (migration-safe: колонки добавляются лениво) ---

def _ensure_columns():
    try:
        cols = [c[1] for c in db.execute("PRAGMA table_info(user_settings)").fetchall()]
    except Exception:
        return
    if "notify_enabled" not in cols:
        try:
            db.execute("ALTER TABLE user_settings ADD COLUMN notify_enabled INTEGER DEFAULT 1")
        except Exception:
            pass
    if "notify_muted_until" not in cols:
        try:
            db.execute("ALTER TABLE user_settings ADD COLUMN notify_muted_until TEXT DEFAULT NULL")
        except Exception:
            pass
    if "notify_msg_id" not in cols:
        try:
            db.execute("ALTER TABLE user_settings ADD COLUMN notify_msg_id INTEGER DEFAULT NULL")
        except Exception:
            pass


def is_notify_enabled(user_id: int) -> bool:
    _ensure_columns()
    try:
        row = db.execute("SELECT notify_enabled FROM user_settings WHERE user_id = ?",
                         (user_id,)).fetchone()
        return row is None or row[0] is None or bool(row[0])
    except Exception:
        return True


def set_notify_enabled(user_id: int, enabled: bool) -> None:
    _ensure_columns()
    db.execute("INSERT INTO user_settings (user_id, notify_enabled) VALUES (?, ?) "
               "ON CONFLICT(user_id) DO UPDATE SET notify_enabled = excluded.notify_enabled",
               (user_id, int(enabled)))
    db.commit()


def mute_until_morning(user_id: int) -> None:
    """Молчать до 08:00 по времени пользователя."""
    _ensure_columns()
    now = user_now(user_id)
    morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now.hour >= 8:
        morning = morning + timedelta(days=1)
    # храним в UTC-наивном ISO + смещение tz, чтобы сравнение было корректным
    db.execute("INSERT INTO user_settings (user_id, notify_muted_until) VALUES (?, ?) "
               "ON CONFLICT(user_id) DO UPDATE SET notify_muted_until = excluded.notify_muted_until",
               (user_id, morning.isoformat()))
    db.commit()


def is_muted(user_id: int) -> bool:
    _ensure_columns()
    try:
        row = db.execute("SELECT notify_muted_until FROM user_settings WHERE user_id = ?",
                         (user_id,)).fetchone()
        if not row or not row[0]:
            return False
        until = datetime.fromisoformat(row[0])
        # naive iso в tz пользователя сравниваем с user_now
        if until.tzinfo is None:
            try:
                from zoneinfo import ZoneInfo
                until = until.replace(tzinfo=ZoneInfo(get_user_timezone(user_id)))
            except Exception:
                pass
        return user_now(user_id) < until
    except Exception:
        return False


def get_last_notify_msg_id(user_id: int) -> Optional[int]:
    # In-memory первым: middleware чистки вызывается при КАЖДОМ сообщении,
    # лишний SELECT в Turso (сеть) на каждое нажатие — неприемлемо.
    try:
        from trackcheck import runtime
        cached = runtime.user_notify_msg.get(user_id)
        if cached:
            return cached
    except Exception:
        pass
    _ensure_columns()
    try:
        row = db.execute("SELECT notify_msg_id FROM user_settings WHERE user_id = ?",
                         (user_id,)).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def set_last_notify_msg_id(user_id: int, msg_id: Optional[int]) -> None:
    try:
        from trackcheck import runtime
        if msg_id:
            runtime.user_notify_msg[user_id] = msg_id
        else:
            runtime.user_notify_msg.pop(user_id, None)
    except Exception:
        pass
    _ensure_columns()
    db.execute("INSERT INTO user_settings (user_id, notify_msg_id) VALUES (?, ?) "
               "ON CONFLICT(user_id) DO UPDATE SET notify_msg_id = excluded.notify_msg_id",
               (user_id, msg_id))
    db.commit()


# --- Context collection ---

def _deadline_days_left(deadline: Optional[str], user_id: int) -> Optional[int]:
    if not deadline:
        return None
    try:
        dl = datetime.strptime(deadline, "%Y-%m-%d").date()
        return (dl - user_today_date(user_id)).days
    except Exception:
        return None


def collect_context(user_id: int) -> dict:
    """Всё нужное для решения важное/обычное + текст. Только чтение БД."""
    from trackcheck.database.repositories import (
        get_tasks_for_today, get_today_ratings, get_diet_profile,
        get_today_calories, get_ai_plan, get_today_plan, get_today_session,
        get_user_name,
    )
    try:
        tasks = get_tasks_for_today(user_id)
    except Exception:
        tasks = []
    open_tasks = [t for t in tasks if not t.get("is_done")]
    important_tasks = []
    for t in open_tasks:
        dl = _deadline_days_left(t.get("deadline"), user_id)
        if t.get("is_priority") or (dl is not None and dl <= 1):
            important_tasks.append(t)

    try:
        today_r = get_today_ratings(user_id)
    except Exception:
        today_r = {}

    # тренировка сегодня?
    workout_pending = False
    try:
        plan = get_ai_plan(user_id)
        today_plan = get_today_plan(plan, user_id) if plan else None
        if today_plan:
            sess = get_today_session(user_id)
            workout_pending = not sess or sess.get("status") != "done"
    except Exception:
        pass

    # диета сильно мимо цели? (>25% недобор/перебор к этому часу дня — грубо:
    # сравниваем факт с пропорциональной нормой)
    diet_off = False
    diet_info = ""
    try:
        profile = get_diet_profile(user_id)
        if profile and profile.get("daily_calories"):
            goal = float(profile["daily_calories"])
            eaten = float(get_today_calories(user_id) or 0)
            now = user_now(user_id)
            frac = max(0.15, (now.hour * 60 + now.minute) / 1440)
            expected = goal * frac
            diet_info = f"{int(eaten)}/{int(goal)} ккал"
            if eaten < expected * 0.5 or eaten > goal * 1.25:
                diet_off = True
    except Exception:
        pass

    try:
        name = get_user_name(user_id)
    except Exception:
        name = "друг"

    missing_ratings = [c for c in ("сон", "еда", "активность", "зависание", "настрой")
                       if c not in today_r]
    return {
        "name": name,
        "open_tasks": open_tasks,
        "important_tasks": important_tasks,
        "missing_ratings": missing_ratings,
        "workout_pending": workout_pending,
        "diet_off": diet_off,
        "diet_info": diet_info,
    }


def is_important(ctx: dict) -> bool:
    """То же правило, что для задач: 🔥/дедлайн<=1 ИЛИ тренировка не сделана
    в тренировочный день ИЛИ диета сильно мимо цели."""
    return bool(ctx["important_tasks"]) or ctx["workout_pending"] or ctx["diet_off"]


def has_anything_to_say(ctx: dict) -> bool:
    return bool(ctx["open_tasks"] or ctx["missing_ratings"]
                or ctx["workout_pending"] or ctx["diet_off"])


# --- Text: AI with fallback chain, template fallback ---

def build_template_text(ctx: dict) -> str:
    parts = []
    if ctx["important_tasks"]:
        titles = ", ".join(f"«{t['title'][:30]}»" for t in ctx["important_tasks"][:3])
        parts.append(f"🔥 Важно: {titles}")
    elif ctx["open_tasks"]:
        n = len(ctx["open_tasks"])
        titles = ", ".join(f"«{t['title'][:30]}»" for t in ctx["open_tasks"][:2])
        parts.append(f"📝 Задачи ({n}): {titles}")
    if ctx["workout_pending"]:
        parts.append("🏋️ Сегодня тренировка — ещё не отмечена")
    if ctx["diet_off"] and ctx["diet_info"]:
        parts.append(f"🍽 Калории: {ctx['diet_info']}")
    if ctx["missing_ratings"]:
        parts.append("📒 Не оценено: " + ", ".join(ctx["missing_ratings"]))
    return " • ".join(parts)[:400] if parts else "Загляни в TrackCheck 👋"


def build_ai_text(ctx: dict) -> tuple[str, bool]:
    """(текст, это_ai). AI через общий fallback Nara->Google; при неудаче — шаблон."""
    from trackcheck.services import ai_service
    tasks_bit = ("нет открытых задач" if not ctx["open_tasks"]
                 else "; ".join(f"{'🔥 ' if t.get('is_priority') else ''}{t['title'][:40]}"
                                + (f" (дедлайн {t['deadline']})" if t.get("deadline") else "")
                                for t in ctx["open_tasks"][:5]))
    prompt = (
        f"Ты — дружелюбный напоминатель трекера привычек. Пользователь: {ctx['name']}. "
        f"Открытые задачи: {tasks_bit}. "
        f"Не оценённые категории сегодня: {', '.join(ctx['missing_ratings']) or 'всё оценено'}. "
        f"Тренировка сегодня не выполнена: {ctx['workout_pending']}. "
        + (f"Калории: {ctx['diet_info']}. " if ctx["diet_info"] else "") +
        "Напиши короткое напоминание (1-2 предложения, по-русски, с 1-2 эмодзи). "
        "Сначала самое важное. Без воды, без markdown."
    )
    try:
        text = ai_service.gemini_generate(prompt, max_tokens=256)
        if text and not text.startswith("❌"):
            return text.strip()[:400], True
    except Exception as e:
        print(f"[NOTIFY] AI error: {e}")
    return build_template_text(ctx), False


# --- Keyboard depends on content ---

def notify_keyboard(ctx: dict):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    btns = []
    if ctx["open_tasks"] or ctx["important_tasks"]:
        btns.append(InlineKeyboardButton(text="📝 Задачи", callback_data="menu_tasks"))
    if ctx["workout_pending"]:
        btns.append(InlineKeyboardButton(text="🏋️ Тренировка", callback_data="menu_workouts"))
    if ctx["diet_off"] or ctx["diet_info"]:
        btns.append(InlineKeyboardButton(text="🍽 Диета", callback_data="menu_diet"))
    if not btns:
        btns.append(InlineKeyboardButton(text="📒 Рефлексия", callback_data="menu_reflection"))
    rows.append(btns)
    rows.append([InlineKeyboardButton(text="🔕 До утра", callback_data="notify_mute")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- Send with single-slot replace ---

async def send_notification(bot, user_id: int, kind: str) -> None:
    """kind: 'hourly' | 'usual'. Проверяет тумблер/мьют, собирает контекст,
    пропускает цикл если сказать нечего (для usual) или не важное (для hourly)."""
    if not is_notify_enabled(user_id) or is_muted(user_id):
        return
    ctx = collect_context(user_id)
    important = is_important(ctx)
    if kind == "hourly" and not important:
        return  # часовой цикл — только важное
    if not has_anything_to_say(ctx):
        return
    # для usual пропускаем если всё важное уже покрыто часовым? нет — шлём,
    # слот один, замена произойдёт ниже
    text, via_ai = build_ai_text(ctx)
    prefix = "🔥 " if important else "🔔 "
    try:
        old_id = get_last_notify_msg_id(user_id)
        if old_id:
            try:
                await bot.delete_message(user_id, old_id)
            except Exception:
                pass
        msg = await bot.send_message(user_id, prefix + text,
                                     reply_markup=notify_keyboard(ctx))
        set_last_notify_msg_id(user_id, msg.message_id)
        log_action(f"NOTIFY_{kind.upper()}", user_id,
                   f"{'ai' if via_ai else 'template'} important={important}")
    except Exception as e:
        print(f"[NOTIFY] send fail user={user_id}: {e}")


async def delete_last_notification(bot, user_id: int) -> None:
    """Удаляет последнее уведомление (при новом / при взаимодействии юзера)."""
    try:
        msg_id = get_last_notify_msg_id(user_id)
        if msg_id:
            try:
                await bot.delete_message(user_id, msg_id)
            except Exception:
                pass
            set_last_notify_msg_id(user_id, None)
    except Exception:
        pass


async def hourly_job(bot) -> None:
    for uid in _notify_audience():
        try:
            await send_notification(bot, uid, "hourly")
        except Exception as e:
            print(f"[NOTIFY] hourly fail user={uid}: {e}")


async def usual_job(bot) -> None:
    for uid in _notify_audience():
        try:
            await send_notification(bot, uid, "usual")
        except Exception as e:
            print(f"[NOTIFY] usual fail user={uid}: {e}")


def _notify_audience() -> list:
    """Все пользователи (шлём бессрочно, пока тумблер включён)."""
    _ensure_columns()
    try:
        rows = db.execute("SELECT user_id FROM user_settings").fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
