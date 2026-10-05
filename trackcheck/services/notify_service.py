"""Персональные напоминания: rule-based шаблоны (без ИИ).

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
import random
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

MANUAL_CATEGORIES = ("сон", "зависание", "настрой")

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
            important_tasks.append({**t, "_days_left": dl})

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
    diet_over = False
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
                diet_over = eaten > goal * 1.25
    except Exception:
        pass

    try:
        name = get_user_name(user_id)
    except Exception:
        name = "друг"

    # Только то, что пользователь оценивает сам: «еда» и «активность» считаются автоматически.
    missing_ratings = [c for c in MANUAL_CATEGORIES if c not in today_r]

    # Серия: только чтение (get_streak сбрасывает её в БД — здесь это не нужно).
    streak, active_today = 0, False
    try:
        row = db.execute("SELECT streak_days, last_active_date FROM user_settings WHERE user_id = ?",
                         (user_id,)).fetchone()
        if row and row[0]:
            today = user_today_str(user_id)
            yesterday = (user_now(user_id) - timedelta(days=1)).strftime("%Y-%m-%d")
            active_today = row[1] == today
            if row[1] in (today, yesterday):
                streak = int(row[0])
    except Exception:
        pass
    try:
        hour = user_now(user_id).hour
    except Exception:
        hour = 12
    return {
        "name": name,
        "open_tasks": open_tasks,
        "important_tasks": important_tasks,
        "missing_ratings": missing_ratings,
        "workout_pending": workout_pending,
        "diet_off": diet_off,
        "diet_over": diet_over,
        "diet_info": diet_info,
        "streak": streak,
        "active_today": active_today,
        "hour": hour,
    }


def is_important(ctx: dict) -> bool:
    """То же правило, что для задач: 🔥/дедлайн<=1 ИЛИ тренировка не сделана
    в тренировочный день ИЛИ диета сильно мимо цели."""
    return bool(ctx["important_tasks"]) or ctx["workout_pending"] or ctx["diet_off"]


def has_anything_to_say(ctx: dict) -> bool:
    return bool(ctx["open_tasks"] or ctx["missing_ratings"]
                or ctx["workout_pending"] or ctx["diet_off"])


# --- Text: rule-based, one focus per notification (no AI) ---
#
# Стиль «как в Duolingo»: короткий жирный заголовок + одна живая строка, один
# понятный призыв. Из всего, что есть сказать, выбираем ОДНУ самую важную тему
# (а не склеиваем всё подряд) — так уведомление читается за секунду.
# Тексты зависят от времени суток; одна и та же формулировка не повторяется дважды подряд.

import html as _html

# Последний показанный вариант по (user, тема) — чтобы не повторяться. Только в памяти.
_last_variant: dict = {}


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def _daypart(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "day"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _q(title: str, limit: int = 40) -> str:
    t = (title or "").strip()
    if len(t) > limit:
        t = t[:limit - 1].rstrip() + "…"
    return "«" + _html.escape(t) + "»"


def _choose(user_id: int, topic: str, variants: list) -> tuple:
    """Случайный вариант, но не тот же, что был в прошлый раз для этой темы."""
    last = _last_variant.get((user_id, topic))
    pool = [v for v in variants if v != last] or variants
    v = random.choice(pool)
    _last_variant[(user_id, topic)] = v
    return v


# Каждая тема: (заголовок, текст). Плейсхолдеры подставляются через .format().
_V_DEADLINE = [
    ("⏰ Дедлайн сегодня", "{title} нужно закрыть до конца дня. Пара минут — и гора с плеч."),
    ("⏰ Сегодня последний день", "{title} ждёт. Сделаешь сейчас — вечер будет свободным."),
]
_V_DEADLINE_TOMORROW = [
    ("⏳ Завтра дедлайн", "{title} — лучше начать сегодня, чем бежать завтра."),
    ("⏳ Осталась одна ночь", "{title} сдаётся завтра. Маленький шаг сегодня?"),
]
_V_PRIORITY = [
    ("🔥 {title} всё ещё ждёт", "Это та самая задача с огоньком. Закроем?"),
    ("🔥 Главное на сегодня", "{title}. Остальное подождёт."),
    ("🔥 Одна важная задача", "{title} — и можно выдохнуть."),
]
_V_WORKOUT = {
    "morning": [
        ("🏋️ Сегодня день тренировки", "План уже готов. Начнёшь пораньше — вечер свободен."),
        ("☀️ Доброе утро, атлет", "Сегодня по плану тренировка. Не забудь бутылку воды 💧"),
    ],
    "day": [
        ("💪 Штанга скучает", "Тренировка на сегодня ещё не отмечена."),
        ("🏋️ Самое время для зала", "Сегодняшняя тренировка ждёт в приложении."),
    ],
    "evening": [
        ("🏋️ Тренировка ещё не сделана", "До конца дня {left}. Даже короткая сессия лучше пропуска."),
        ("💪 Последний шанс сегодня", "Отметь хотя бы пару упражнений — прогресс любит регулярность."),
    ],
    "night": [
        ("🌙 Сегодня по плану тренировка", "Сначала выспись — а потом в зал 💪"),
    ],
}
_V_STREAK_RISK = [
    ("🔥 Серия {n} {days} под угрозой", "Заполни чек-ин за минуту — и огонь не погаснет."),
    ("🔥 Не дай серии сгореть", "{n} {days} подряд! Одна минута на чек-ин — и завтра будет {n1}."),
    ("😬 Огонёк гаснет…", "Серия {n} {days} закончится в полночь. Спасёшь её?"),
]
_V_STREAK_KEEP = [
    ("🔥 {n} {days} подряд", "Продолжим? Сегодняшний чек-ин ещё впереди."),
    ("🔥 Ты в ударе: {n} {days} подряд", "Отметь сегодняшний день, чтобы серия росла."),
]
_V_CHECKIN_ALL = {
    "morning": [
        ("☀️ Как спалось?", "Начни день с чек-ина — сон уже можно оценить."),
        ("☀️ Новый день — новая отметка", "Оцени, как спалось, остальное — по ходу дня."),
    ],
    "day": [
        ("📒 Минутка на себя", "Сон, зависание, настрой — как сегодня?"),
        ("📒 Как идёт день?", "3 быстрые оценки — и чек-ин готов."),
    ],
    "evening": [
        ("📒 Как прошёл день?", "3 быстрые оценки — минута, и чек-ин готов."),
        ("📒 Подведём итоги?", "Оцени день, пока он свеж в памяти."),
    ],
    "night": [
        ("🌙 Новый день начался", "Утром оцени, как спалось — это первая отметка дня."),
    ],
}
_V_CHECKIN_SOME = [
    ("📒 Почти готово", "Осталось: {cats} — и чек-ин закрыт ✨"),
    ("📒 Ещё чуть-чуть", "Не хватает только: {cats}."),
]
_V_DIET_UNDER = [
    ("🍽 Ты сегодня ел?", "Пока {info}. Запиши приём пищи — можно просто сфоткать тарелку."),
    ("🍽 Дневник питания пустоват", "Сейчас {info}. Не забудь записать, что ел."),
]
_V_DIET_OVER = [
    ("🍽 Калорий уже с запасом", "{info}. Ужин полегче — и день в норме."),
    ("🍽 Норма уже позади", "{info}. Завтра выровняем 😉"),
]
_V_TASKS = [
    ("📝 {n} {tasks} на сегодня", "Начни с {title} — дальше пойдёт легче."),
    ("📝 Список ждёт", "{title} и ещё {rest}. По одной — и всё закрыто."),
]
_V_FALLBACK = [
    ("👋 Загляни в TrackCheck", "Пара минут на себя — и день под контролем."),
    ("✨ Как ты там?", "Загляни в приложение — отметь, как прошёл день."),
]

# Кнопка-призыв по теме: (текст, вкладка Mini App).
_CTA = {
    "deadline": ("📝 Открыть задачи", "tasks"),
    "priority": ("📝 Открыть задачи", "tasks"),
    "tasks": ("📝 Открыть задачи", "tasks"),
    "workout": ("💪 К тренировке", "workout"),
    "streak": ("🔥 Спасти серию", "checkin"),
    "streak_keep": ("🔥 Продолжить серию", "checkin"),
    "checkin": ("📒 Отметить день", "checkin"),
    "diet": ("🍽 Открыть питание", "diet"),
    "fallback": ("🚀 Открыть TrackCheck", None),
}


def pick_topic(ctx: dict) -> str:
    """Одна тема по приоритету: дедлайны → огонёк → тренировка → серия → чек-ин → диета → задачи.
    Серия: вечером «под угрозой», днём «продолжим?», ночью не упоминаем (день только начался)."""
    imp = ctx["important_tasks"]
    if any(t.get("_days_left") is not None and t["_days_left"] <= 1 for t in imp):
        return "deadline"
    if imp:
        return "priority"
    if ctx["workout_pending"]:
        return "workout"
    if ctx.get("streak", 0) >= 2 and not ctx.get("active_today") and ctx["missing_ratings"]:
        part = _daypart(ctx.get("hour", 12))
        if part == "evening":
            return "streak"        # серия сгорит в полночь
        if part in ("morning", "day"):
            return "streak_keep"   # мягкое «продолжим?»
    if ctx["missing_ratings"]:
        return "checkin"
    if ctx["diet_off"] and ctx["diet_info"]:
        return "diet"
    if ctx["open_tasks"]:
        return "tasks"
    return "fallback"


def build_message(user_id: int, ctx: dict) -> tuple:
    """-> (HTML-текст, тема)."""
    topic = pick_topic(ctx)
    part = _daypart(ctx.get("hour", 12))
    kw = {}
    if topic == "deadline":
        t = min((t for t in ctx["important_tasks"] if t.get("_days_left") is not None),
                key=lambda t: t["_days_left"])
        variants = _V_DEADLINE if t["_days_left"] <= 0 else _V_DEADLINE_TOMORROW
        kw["title"] = _q(t["title"])
    elif topic == "priority":
        variants = _V_PRIORITY
        kw["title"] = _q(ctx["important_tasks"][0]["title"], 32)
    elif topic == "workout":
        variants = _V_WORKOUT[part]
        left = max(1, 24 - ctx.get("hour", 12))
        kw["left"] = f"{left} {_plural(left, 'час', 'часа', 'часов')}"
    elif topic in ("streak", "streak_keep"):
        n = ctx["streak"]
        variants = _V_STREAK_RISK if topic == "streak" else _V_STREAK_KEEP
        kw.update(n=n, n1=n + 1, days=_plural(n, "день", "дня", "дней"))
    elif topic == "checkin":
        miss = ctx["missing_ratings"]
        if len(miss) == len(MANUAL_CATEGORIES):
            variants = _V_CHECKIN_ALL[part]
        else:
            variants = _V_CHECKIN_SOME
            kw["cats"] = ", ".join(miss)
    elif topic == "diet":
        variants = _V_DIET_OVER if ctx.get("diet_over") else _V_DIET_UNDER
        kw["info"] = ctx["diet_info"]
    elif topic == "tasks":
        n = len(ctx["open_tasks"])
        variants = _V_TASKS if n > 1 else _V_TASKS[:1]
        kw.update(n=n, tasks=_plural(n, "задача", "задачи", "задач"),
                  title=_q(ctx["open_tasks"][0]["title"], 32), rest=n - 1)
    else:
        variants = _V_FALLBACK
    head, body = _choose(user_id, topic, variants)
    text = f"<b>{head.format(**kw)}</b>\n{body.format(**kw)}"
    return text, topic


def build_template_text(ctx: dict) -> str:
    """Совместимость: plain-текст без разметки."""
    import re
    text, _ = build_message(0, ctx)
    return _html.unescape(re.sub(r"</?b>", "", text))


# --- Keyboard: one call-to-action straight into the Mini App + mute ---

def notify_keyboard(ctx: dict, topic: Optional[str] = None):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    from trackcheck.config import MINIAPP_URL
    label, tab = _CTA.get(topic or pick_topic(ctx), _CTA["fallback"])
    url = f"{MINIAPP_URL}?tab={tab}" if tab else MINIAPP_URL
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton(text="🔕 До утра", callback_data="notify_mute")],
    ])


# --- Send with single-slot replace ---

async def send_notification(bot, user_id: int, kind: str) -> None:
    """kind: 'hourly' | 'usual'. Проверяет тумблер/мьют, собирает контекст,
    пропускает цикл если сказать нечего (для usual) или не важное (для hourly)."""
    from trackcheck.utils.concurrency import run_db
    enabled = await run_db(is_notify_enabled, user_id)
    muted = await run_db(is_muted, user_id)
    if not enabled or muted:
        return
    ctx = await run_db(collect_context, user_id)
    important = is_important(ctx)
    if kind == "hourly" and not important:
        return  # часовой цикл — только важное
    if not has_anything_to_say(ctx):
        return
    # для usual пропускаем если всё важное уже покрыто часовым? нет — шлём,
    # слот один, замена произойдёт ниже.
    text, topic = build_message(user_id, ctx)
    try:
        old_id = await run_db(get_last_notify_msg_id, user_id)
        if old_id:
            try:
                await bot.delete_message(user_id, old_id)
            except Exception:
                pass
        msg = await bot.send_message(user_id, text, parse_mode="HTML",
                                     reply_markup=notify_keyboard(ctx, topic))
        await run_db(set_last_notify_msg_id, user_id, msg.message_id)
        log_action(f"NOTIFY_{kind.upper()}", user_id,
                   f"template topic={topic} important={important}")
    except Exception as e:
        print(f"[NOTIFY] send fail user={user_id}: {e}")


async def delete_last_notification(bot, user_id: int) -> None:
    """Удаляет последнее уведомление (при новом / при взаимодействии юзера).

    Только in-memory кэш — без похода в БД, чтобы middleware не добавляла
    сетевой запрос к КАЖДОМУ нажатию кнопки."""
    try:
        from trackcheck import runtime
        msg_id = runtime.user_notify_msg.get(user_id)
        if msg_id:
            try:
                await bot.delete_message(user_id, msg_id)
            except Exception:
                pass
            runtime.user_notify_msg.pop(user_id, None)
            # БД чистим фоном, не задерживая обработку апдейта.
            import asyncio
            from trackcheck.utils.concurrency import run_db as _run_db
            asyncio.create_task(_run_db(set_last_notify_msg_id, user_id, None))
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
