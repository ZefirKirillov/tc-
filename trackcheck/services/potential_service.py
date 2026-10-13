"""«Реализованный потенциал» — дневная сумма из 40 баллов и разбор её плато/спадов.

  самочувствие (среднее «сон», «зависание», «настрой») 0–10
+ питание («еда»)                                       0–10
+ тренировка («активность»)                             0–10
+ тело (оценка по фото)                                 0–10

Пропуски: категория, которую сегодня не оценили, берётся с последнего дня, когда
она была; оценка тела действует до следующего фото. День без единой оценки — это
пропуск: линия держится на уровне последнего настоящего дня (filled=True, рисуется
пунктиром) и в поиске плато/спадов не участвует.
"""
import bisect
import hashlib
import json
from datetime import timedelta
from typing import Dict, List, Optional

MAX_TOTAL = 40
CATEGORIES = ("сон", "зависание", "настрой", "еда", "активность")
WELLBEING = ("сон", "зависание", "настрой")
PARTS = ("wellbeing", "diet", "training", "body")

# Спад: настоящий день на DROP+ баллов ниже пика за последние PEAK_WINDOW дней;
# отрезок — от пика до дна.
DROP = 6
PEAK_WINDOW = 5
# Плато: PLATEAU_MIN+ настоящих дней в коридоре PLATEAU_BAND баллов, и ниже потолка
# (держаться на 36/40 — не проблема).
PLATEAU_MIN = 5
PLATEAU_BAND = 3
PLATEAU_CEILING = 34

# Для переноса оценок в начало окна смотрим назад дальше видимого периода.
LOOKBACK_DAYS = 30
# Не больше стольких новых ИИ-разборов за один запрос.
MAX_NEW_NOTES = 4

LABELS = {
    "сон": "сон", "зависание": "зависание", "настрой": "настрой",
    "еда": "питание", "активность": "тренировка", "тело": "тело",
}

TIPS = {
    "сон": "Ложись в одно и то же время и убирай телефон за час до сна.",
    "зависание": "Поставь лимит на соцсети и игры и держи телефон вне досягаемости, пока работаешь.",
    "настрой": "Начинай день с одной маленькой задачи, которую точно доделаешь.",
    "еда": "Планируй приёмы пищи заранее и вноси еду сразу — так проще попадать в норму.",
    "активность": "Не пропускай тренировки подряд: тяжело — сделай облегчённую версию, но сделай.",
    "тело": "Тело меняется медленно: держи питание и тренировки ровными и обновляй фото раз в 2–4 недели.",
}


def _r1(x: float) -> float:
    return round(x + 1e-9, 1)


# ---------- series ----------

def build_series(dates: List[str], ratings_by_date: Dict[str, dict],
                 body_history: List[tuple]) -> List[dict]:
    """Чистая функция. dates — подряд идущие дни по возрастанию;
    ratings_by_date — {date: {category: rating}}; body_history — [(date, score)] по возрастанию.
    → [{date, total, filled, parts, values}], total=None до первого настоящего дня."""
    body_dates = [d for d, _ in body_history]
    known: Dict[str, Optional[float]] = {c: None for c in CATEGORIES}
    last: Optional[dict] = None
    out = []
    for date in dates:
        day = {c: v for c, v in (ratings_by_date.get(date) or {}).items() if c in CATEGORIES}
        if not day:
            if last is None:
                out.append({"date": date, "total": None, "filled": True, "parts": None, "values": None})
            else:
                out.append({**last, "date": date, "filled": True})
            continue
        known.update(day)
        i = bisect.bisect_right(body_dates, date)
        body = body_history[i - 1][1] if i else 0
        wb_vals = [known[c] for c in WELLBEING if known[c] is not None]
        parts = {
            "wellbeing": _r1(sum(wb_vals) / len(wb_vals)) if wb_vals else 0,
            "diet": known["еда"] or 0,
            "training": known["активность"] or 0,
            "body": body,
        }
        values = {**{c: known[c] for c in CATEGORIES}, "тело": body or None}
        last = {"date": date, "total": _r1(sum(parts.values())), "filled": False,
                "parts": parts, "values": values}
        out.append(last)
    return out


# ---------- plateaus and drawbacks ----------

def find_segments(series: List[dict]) -> List[dict]:
    """Чистая функция. → [{kind: 'drawback'|'plateau', start, end, from, to}] по дате начала.
    Ищет только по настоящим дням; пропуски внутри отрезка допустимы."""
    pts = [(p["date"], p["total"]) for p in series if not p["filled"] and p["total"] is not None]
    vals = [v for _, v in pts]
    n = len(vals)
    segs = []
    in_drawback = [False] * n

    i, floor = 1, 0  # floor — дно прошлого спада: пик ищем только после него
    while i < n:
        lo = max(floor, i - PEAK_WINDOW)
        peak = max(vals[lo:i])
        p = max(k for k in range(lo, i) if vals[k] == peak)  # последний пик — начало спада
        if vals[i] <= peak - DROP:
            # спад — от пика до дна, пока линия падает; застрял внизу — это уже плато
            j = i
            while j + 1 < n and vals[j + 1] < vals[j]:
                j += 1
            segs.append({"kind": "drawback", "start": pts[p][0], "end": pts[j][0],
                         "from": vals[p], "to": vals[j]})
            for k in range(p, j + 1):
                in_drawback[k] = True
            floor = j
            i = j + 1
        else:
            i += 1

    i = 0
    while i < n:
        if in_drawback[i]:
            i += 1
            continue
        j = i
        while (j + 1 < n and not in_drawback[j + 1]
               and max(vals[i:j + 2]) - min(vals[i:j + 2]) <= PLATEAU_BAND):
            j += 1
        mean = sum(vals[i:j + 1]) / (j - i + 1)
        if j - i + 1 >= PLATEAU_MIN and mean < PLATEAU_CEILING:
            segs.append({"kind": "plateau", "start": pts[i][0], "end": pts[j][0],
                         "from": vals[i], "to": vals[j], "level": _r1(mean)})
            i = j + 1
        else:
            i += 1

    return sorted(segs, key=lambda s: s["start"])


def _segment_days(series: List[dict], seg: dict) -> List[dict]:
    return [p for p in series if seg["start"] <= p["date"] <= seg["end"] and not p["filled"]]


def segment_signature(series: List[dict], seg: dict) -> str:
    """Меняется, если поменялись данные отрезка — тогда разбор пишется заново."""
    raw = json.dumps([(p["date"], p["values"]) for p in _segment_days(series, seg)],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(f"{seg['kind']}|{raw}".encode("utf-8")).hexdigest()[:16]


def _fmt(x) -> str:
    x = _r1(float(x))
    return (str(int(x)) if x == int(x) else str(x)).replace(".", ",")


def segment_facts(series: List[dict], seg: dict) -> dict:
    """Чистая функция: что изменилось на отрезке, по категориям.
    drawback → {changes: [(cat, было, стало)] от самого большого падения};
    plateau → {weakest: [(cat, среднее)] от самого слабого}."""
    days = _segment_days(series, seg)
    cats = list(CATEGORIES) + ["тело"]
    if seg["kind"] == "drawback":
        first = days[0]["values"]
        trough = min(days[1:] or days, key=lambda p: p["total"])["values"]
        changes = [(c, first[c], trough[c]) for c in cats
                   if first.get(c) is not None and trough.get(c) is not None and trough[c] < first[c]]
        changes.sort(key=lambda x: x[2] - x[1])
        return {"changes": changes}
    avgs = []
    for c in cats:
        vs = [p["values"][c] for p in days if p["values"].get(c) is not None]
        avgs.append((c, sum(vs) / len(vs) if vs else 0))
    avgs.sort(key=lambda x: x[1])
    return {"weakest": avgs}


def fallback_note(series: List[dict], seg: dict) -> dict:
    """Разбор без ИИ — если ИИ недоступен. Те же факты, готовый совет."""
    facts = segment_facts(series, seg)
    if seg["kind"] == "drawback":
        top = facts["changes"][:2]
        what = f"Потенциал упал с {_fmt(seg['from'])} до {_fmt(seg['to'])} из {MAX_TOTAL}"
        if top:
            what += ": " + ", ".join(f"{LABELS[c]} {_fmt(a)}→{_fmt(b)}" for c, a, b in top)
        cat = top[0][0] if top else "настрой"
    else:
        n = len(_segment_days(series, seg))
        weak = facts["weakest"][:2]
        what = (f"{n} дн. на уровне ~{_fmt(seg['level'])} из {MAX_TOTAL}, слабее всего — "
                + " и ".join(f"{LABELS[c]} (≈{_fmt(v)}/10)" for c, v in weak))
        cat = weak[0][0] if weak else "настрой"
    return {"what": what + ".", "fix": TIPS[cat]}


def note_prompt(name: str, series: List[dict], seg: dict) -> str:
    days = _segment_days(series, seg)
    table = "\n".join(
        f"{p['date']}: итог {_fmt(p['total'])}/40; "
        + ", ".join(f"{LABELS[c]} {_fmt(v)}" for c, v in p["values"].items() if v is not None)
        for p in days)
    if seg["kind"] == "drawback":
        kind = f"СПАД: с {_fmt(seg['from'])} до {_fmt(seg['to'])} из 40"
    else:
        kind = f"ПЛАТО: {len(days)} дн. на уровне ~{_fmt(seg['level'])} из 40, без роста"
    return f"""Ты Check — коуч в трекере привычек. Пользователь: {name}.
Каждый день он получает «реализованный потенциал» из 40 баллов:
самочувствие (среднее сна, зависания и настроя, 0–10) + питание (0–10, насколько попал в норму калорий)
+ тренировка (0–10, насколько выполнил план; 5 — день отдыха) + тело (оценка фото, 0–10).
Все оценки: 10 — лучше всего. «Зависание» 10 = почти не залипал в телефон и игры.

На графике найден отрезок — {kind}.
Оценки по дням:
{table}

Объясни, что произошло (по цифрам, какие части потянули вниз или стоят на месте),
и как не допустить такого снова — один-два конкретных действия.
Пиши на «ты», коротко, без воды. Верни ТОЛЬКО JSON:
{{"what": "1–2 предложения: что произошло", "fix": "1–2 предложения: что делать"}}"""


# ---------- DB-aware ----------

def _load(user_id: int, days: int) -> List[dict]:
    from trackcheck.database.repositories import get_daily_ratings, get_body_score_history
    from trackcheck.utils.dates import user_today_date
    span = days + LOOKBACK_DAYS
    today = user_today_date(user_id)
    dates = [(today - timedelta(days=span - 1 - i)).strftime("%Y-%m-%d") for i in range(span)]
    by_date: Dict[str, dict] = {}
    for day_date, category, rating in get_daily_ratings(user_id, span):
        by_date.setdefault(day_date, {})[category] = rating
    return build_series(dates, by_date, get_body_score_history(user_id))[-days:]


def get_potential(user_id: int, days: int) -> dict:
    """Ряд за days дней + отрезки с сохранёнными разборами (note=None — разбора ещё нет)."""
    from trackcheck.database.repositories import get_potential_notes
    series = _load(user_id, days)
    notes = get_potential_notes(user_id)
    segments = []
    for seg in find_segments(series):
        sig = segment_signature(series, seg)
        segments.append({**seg, "signature": sig,
                         "note": notes.get((seg["kind"], seg["start"], seg["end"], sig))})
    return {"max": MAX_TOTAL, "series": series, "segments": segments}


def explain_segments(user_id: int, days: int) -> List[dict]:
    """Дописывает недостающие разборы (ИИ, медленно — вызывать в потоке).
    Если ИИ не ответил — разбор по правилам, не сохраняется (повторим в следующий раз)."""
    from trackcheck.database.repositories import save_potential_note, get_user_name
    from trackcheck.services.ai_service import gemini_generate_json, _parse_json_response
    data = get_potential(user_id, days)
    series = data["series"]
    missing = [s for s in data["segments"] if s["note"] is None]
    for seg in missing[-MAX_NEW_NOTES:]:
        parsed = _parse_json_response(
            gemini_generate_json(note_prompt(get_user_name(user_id), series, seg), 1024))
        what = str((parsed or {}).get("what") or "").strip()
        fix = str((parsed or {}).get("fix") or "").strip()
        if what and fix:
            save_potential_note(user_id, seg["kind"], seg["start"], seg["end"], seg["signature"],
                                what[:600], fix[:600])
            seg["note"] = {"what": what[:600], "fix": fix[:600]}
    for seg in data["segments"]:
        if seg["note"] is None:
            seg["note"] = {**fallback_note(series, seg), "fallback": True}
    return data["segments"]
