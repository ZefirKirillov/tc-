import base64
import inspect
import json
import os
import re
import time
import urllib.request
from typing import Optional

try:
    from google import genai
    from google.genai import types
    _GOOGLE_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    _GOOGLE_AVAILABLE = False

from trackcheck.database.repositories import (
    get_ratings, get_daily_ratings, get_today_ratings, get_yesterday_ratings,
    get_or_create_workout_data, get_or_create_rank_data, get_diet_profile,
    get_today_calories, get_today_food_log, get_last_weight, get_tasks_for_today,
    get_user_name, db,
)
from trackcheck.utils.formatting import strip_markdown


NARA_BASE_URL = os.environ.get("NARA_BASE_URL", "https://router.bynara.id/v1").rstrip("/")
NARA_MODEL = os.environ.get("NARA_MODEL", "ling-3.0-flash-vl-free")
GOOGLE_MODEL = os.environ.get("GOOGLE_MODEL", "gemini-3.6-flash")


def _nara_api_key(ratings: bool = False) -> Optional[str]:
    if ratings:
        return (
            os.environ.get("NARA_API_KEY_RATINGS")
            or os.environ.get("NARA_API_RATINGS")
            or os.environ.get("NARA_API")
        )
    return os.environ.get("NARA_API") or os.environ.get("NARA_API_KEY")


def _google_api_key(ratings: bool = False) -> Optional[str]:
    if ratings:
        return os.environ.get("GOOGLE_API_KEY_RATINGS") or os.environ.get("GEMINI_API_KEY_RATINGS")
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")


# Имя последнего сработавшего провайдера/модели — для логов и отладки.
# Обновляется каждым вызовом _generate_text: {'provider': 'nara'|'google'|None,
# 'model': ..., 'reason': ...}. reason объясняет, почему Nara не сработала
# и произошёл fallback (или почему не сработал никто).
LAST_AI_CALL: dict = {"provider": None, "model": None, "reason": None}


def _auto_caller() -> str:
    """Имя ближайшего публичного gemini_*/analyze_* вызова в стеке.

    Позволяет в логе [AI-ROUTE] видеть, какая фича бота сделала запрос
    (план тренировок, оценка настроения, разбор фото и т.д.), без ручной
    передачи caller= через всю цепочку вызовов."""
    try:
        for frame in inspect.stack()[2:]:
            name = frame.function
            if (name.startswith("gemini_") or name.startswith("analyze_")) \
                    and not name.startswith("_"):
                return name
    except Exception:
        pass
    return "?"


def _log_ai_call(caller: str, detail: str = "") -> None:
    info = LAST_AI_CALL
    msg = (f"[AI-ROUTE] caller={caller} provider={info.get('provider')} "
           f"model={info.get('model')} reason={info.get('reason')}")
    if detail:
        msg += f" | {detail}"
    print(msg)


def _nara_chat(prompt: str, max_tokens: int, image_bytes: Optional[bytes] = None,
               api_key: Optional[str] = None) -> Optional[str]:
    """Прямой вызов NaraRouter через OpenAI-совместимый /chat/completions.

    Возвращает текст ответа или None. Причину неудачи пишет в
    LAST_AI_CALL['reason']: 'no_key' | 'empty' | 'http_<code>: <body>' |
    'exception: <ClassName>: <msg>'."""
    key = api_key if api_key is not None else _nara_api_key()
    if not key:
        LAST_AI_CALL.update(provider=None, model=None, reason="no_key")
        return None
    if isinstance(image_bytes, bytes) and len(image_bytes) == 0:
        image_bytes = None
    started = time.monotonic()
    try:
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            content: object = [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]
        else:
            content = prompt
        payload = {
            "model": NARA_MODEL,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{NARA_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = getattr(resp, "status", "?")
            body = json.loads(resp.read().decode("utf-8"))
        elapsed = time.monotonic() - started
        # Какая модель реально ответила: доверяем полю "model" из ответа
        # роутера (может отличаться от запрошенной при remap на стороне Nara).
        served_model = body.get("model") or NARA_MODEL
        choices = body.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            text = (msg.get("content") or "").strip()
            if text:
                LAST_AI_CALL.update(provider="nara", model=served_model,
                                    reason=f"ok http={status} {elapsed:.1f}s "
                                           f"finish={choices[0].get('finish_reason')}")
                print(f"[NARA] OK model={served_model} http={status} "
                      f"{elapsed:.1f}s ({len(text)} chars)")
                return text
        LAST_AI_CALL.update(provider=None, model=served_model,
                            reason=f"empty http={status} {elapsed:.1f}s "
                                   f"body={repr(str(body)[:200])}")
        print(f"[NARA] Пустой ответ от роутера (model={served_model}): "
              f"{repr(str(body)[:200])}")
        return None
    except Exception as e:
        import traceback
        elapsed = time.monotonic() - started
        reason = _describe_http_error(e)
        LAST_AI_CALL.update(provider=None, model=NARA_MODEL,
                            reason=f"{reason} after={elapsed:.1f}s")
        print(f"[NARA] Ошибка ({reason}, {elapsed:.1f}s): {e}")
        traceback.print_exc()
        return None


def _describe_http_error(e: Exception) -> str:
    """Короткое объяснение HTTP-ошибки: статус + тело ответа, если есть."""
    status = getattr(e, "code", None) or getattr(e, "status", None)
    body = ""
    try:
        raw = e.read() if hasattr(e, "read") else None
        if raw:
            body = raw.decode("utf-8", errors="replace")[:300]
    except Exception:
        pass
    if status:
        hint = ""
        if status == 401:
            hint = " (неверный/отсутствующий NARA_API?)"
        elif status == 402:
            hint = " (кончились кредиты/квота на роутере?)"
        elif status == 404:
            hint = f" (модель '{NARA_MODEL}' не найдена на роутере?)"
        elif status == 429:
            hint = " (rate limit — слишком много запросов?)"
        elif status == 400:
            hint = " (роутер отклонил payload — max_tokens/vision формат?)"
        elif int(status) >= 500:
            hint = " (ошибка на стороне роутера/провайдера)"
        return f"http_{status}{hint} body={body!r}" if body else f"http_{status}{hint}"
    return f"exception: {type(e).__name__}: {e}"


def _google_generate(prompt: str, max_tokens: int, image_bytes: Optional[bytes] = None,
                     think_off: bool = False, api_key: Optional[str] = None) -> Optional[str]:
    """Fallback на прямой Google API. Возвращает None при ошибке/отсутствии ключа.
    Успех/неудачу пишет в LAST_AI_CALL (не затирает reason от Nara при успехе —
    дописывает его как fallback_reason)."""
    if not _GOOGLE_AVAILABLE:
        LAST_AI_CALL.update(provider=None, model=None,
                            reason=(LAST_AI_CALL.get("reason") or "n/a")
                            + " + google_unavailable (пакет google-genai не установлен)")
        print("[GEMINI] Fallback пропущен: пакет google-genai не установлен.")
        return None
    key = api_key if api_key is not None else _google_api_key()
    if not key:
        prev = LAST_AI_CALL.get("reason") or "n/a"
        LAST_AI_CALL.update(provider=None, model=None,
                            reason=f"{prev} + google_no_key (GOOGLE_API_KEY не задан)")
        print("[GEMINI] Fallback пропущен: нет GOOGLE_API_KEY.")
        return None
    started = time.monotonic()
    try:
        client = genai.Client(api_key=key)
        kwargs = {"max_output_tokens": max_tokens}
        if think_off:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        config = types.GenerateContentConfig(**kwargs)
        if image_bytes:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type='image/png')
            contents = [image_part, prompt]
        else:
            contents = prompt
        response = client.models.generate_content(
            model=GOOGLE_MODEL,
            contents=contents,
            config=config,
        )
        elapsed = time.monotonic() - started
        text = (getattr(response, 'text', None) or "").strip()
        if not text and response.candidates and response.candidates[0].content.parts:
            text = response.candidates[0].content.parts[0].text.strip()
        if text:
            prev = LAST_AI_CALL.get("reason")
            suffix = f" + fallback_reason: {prev}" if prev else ""
            LAST_AI_CALL.update(provider="google", model=GOOGLE_MODEL,
                                reason=f"ok {elapsed:.1f}s{suffix}")
            print(f"[GEMINI] OK (fallback) model={GOOGLE_MODEL} {elapsed:.1f}s "
                  f"({len(text)} chars)")
            return text
        LAST_AI_CALL.update(provider=None, model=GOOGLE_MODEL,
                            reason=f"google_empty {elapsed:.1f}s "
                                   f"(Nara: {LAST_AI_CALL.get('reason')})")
        print(f"[GEMINI] Пустой ответ от fallback-модели {GOOGLE_MODEL}.")
        return None
    except Exception as e:
        import traceback
        elapsed = time.monotonic() - started
        prev = LAST_AI_CALL.get("reason")
        suffix = f" + fallback_reason: {prev}" if prev else ""
        LAST_AI_CALL.update(provider=None, model=GOOGLE_MODEL,
                            reason=f"google_exception: {type(e).__name__}: {e} "
                                   f"after={elapsed:.1f}s{suffix}")
        print(f"[GEMINI] Ошибка (fallback, {elapsed:.1f}s): {e}")
        traceback.print_exc()
        return None


def _generate_text(prompt: str, max_tokens: int = 8192, image_bytes: Optional[bytes] = None,
                   think_off: bool = False, rating_key: bool = False,
                   caller: Optional[str] = None) -> Optional[str]:
    """NaraRouter — первичный провайдер, Google — fallback.

    Каждый вызов пишет одну итоговую строку [AI-ROUTE] в лог: кто вызвал,
    какой провайдер/модель реально ответили и почему случился fallback."""
    caller = caller or _auto_caller()
    text = _nara_chat(prompt, max_tokens, image_bytes,
                      api_key=_nara_api_key(ratings=rating_key))
    if text:
        _log_ai_call(caller)
        return text
    nara_reason = LAST_AI_CALL.get("reason")
    if _nara_api_key(ratings=rating_key):
        print(f"[AI] NaraRouter не ответил ({nara_reason}) — пробую Google fallback.")
    text = _google_generate(prompt, max_tokens, image_bytes, think_off,
                            api_key=_google_api_key(ratings=rating_key))
    _log_ai_call(caller)
    return text


def gemini_generate(prompt: str, max_tokens: int = 8192, raw: bool = False) -> str:
    """Синхронный вызов ИИ (NaraRouter — первично, Google — fallback).
    raw=True — не применять strip_markdown (для JSON-ответов)."""
    if not _nara_api_key() and not _google_api_key():
        return "❌ ИИ недоступен (нет API-ключа). Установи NARA_API."
    text = _generate_text(prompt, max_tokens)
    if not text:
        return "❌ ИИ не вернул ответ (возможно, сработала фильтрация)."
    if raw:
        print(f"[AI] Raw response ({len(text)} chars): {repr(text[:200])}")
        return text
    return strip_markdown(text)



def gemini_generate_json(prompt: str, max_tokens: int = 8192) -> str:
    """Вызов ИИ для JSON-ответов."""
    if not _nara_api_key() and not _google_api_key():
        return ""
    text = _generate_text(prompt, max_tokens, think_off=True)
    if text:
        print(f"[AI_JSON] Response ({len(text)} chars): {repr(text[:200])}")
        return text
    return ""



def gemini_generate_rating(prompt: str, max_tokens: int = 1024) -> Optional[dict]:
    """Авто-оценка категорий через отдельный ключ (NARA_API_RATINGS/NARA_API,
    fallback — GOOGLE_API_KEY_RATINGS). Модель должна ответить JSON
    {"rating": 1-10, "comment"/"response": "..."}. Возвращает None если
    ключ не настроен или запрос не удался — вызывающий код должен в этом случае
    откатиться на ручной ввод оценки, а не выдумывать число."""
    if not _nara_api_key(ratings=True) and not _google_api_key(ratings=True):
        return None
    text = _generate_text(prompt, max_tokens, think_off=True, rating_key=True)
    if not text:
        print("[AI-RATINGS] Пустой ответ от модели.")
        return None
    try:
        text = text.strip()
        text = re.sub(r'^```json\s*|\s*```$', '', text).strip()
        data = json.loads(text)
        rating = max(1, min(10, int(round(float(data.get('rating'))))))
        # разные промпты просят модель назвать поле по-разному ('comment' у Еды/Активности,
        # 'response' у Настроя) - читаем любое из них, чтобы текст не терялся
        comment = str(data.get('comment') or data.get('response') or '').strip()
        return {'rating': rating, 'comment': comment}
    except Exception as e:
        import traceback
        print(f"[AI-RATINGS] Ошибка ({type(e).__name__}): {e}")
        print(f"[AI-RATINGS] Ответ модели, который не удалось разобрать: {repr(text[:300])}")
        traceback.print_exc()
        return None



def analyze_food_photo(image_bytes: bytes, prompt: str) -> Optional[str]:
    """Распознавание блюда/калорий по фото. Возвращает None при ошибке,
    чтобы вызывающий код мог показать кнопку повтора."""
    if not image_bytes:
        return None
    if not _nara_api_key() and not _google_api_key():
        return None
    try:
        return _generate_text(prompt, 256, image_bytes=image_bytes)
    except Exception as e:
        import traceback
        print(f"[FOOD PHOTO] Ошибка: {e}")
        traceback.print_exc()
        return None


def analyze_body_photo(image_bytes: bytes, prompt: str, max_tokens: int = 2048) -> Optional[str]:
    """Анализ фото телосложения (NaraRouter первично, Google fallback)."""
    if not image_bytes:
        return None
    if not _nara_api_key() and not _google_api_key():
        return None
    return _generate_text(prompt, max_tokens, image_bytes=image_bytes)



def get_user_stats_for_ai(user_id: int) -> dict:
    ratings_7d = get_ratings(user_id, days=7)
    ratings_30d = get_ratings(user_id, days=30)
    workout_data = get_or_create_workout_data(user_id)
    rank_data = get_or_create_rank_data(user_id)
    yesterday = get_yesterday_ratings(user_id)
    return {
        'today': get_today_ratings(user_id),
        'yesterday': yesterday,
        'week_avg': {cat: avg for cat, avg, _ in ratings_7d},
        'month_avg': {cat: avg for cat, avg, _ in ratings_30d},
        'workouts': workout_data,
        'rank': rank_data
    }



def get_full_context_for_ai(user_id: int) -> str:
    """Собирает свежую сводку по рефлексии, диете, тренировкам и задачам,
    чтобы ответы и советы ИИ были персонализированы под конкретного пользователя."""
    lines = []

    # --- Рефлексия ---
    stats = get_user_stats_for_ai(user_id)
    today_r = stats['today']
    yesterday_r = stats['yesterday']
    week_avg = stats['week_avg']
    if today_r:
        lines.append("Рефлексия сегодня: " + ", ".join(f"{cat} {val}/10" for cat, val in today_r.items()))
    else:
        lines.append("Рефлексия сегодня: ещё не заполнена.")
    if yesterday_r:
        lines.append("Рефлексия вчера: " + ", ".join(f"{cat} {val}/10" for cat, val in yesterday_r.items()))
    if week_avg:
        lines.append("Средние оценки за 7 дней: " + ", ".join(f"{cat} {val:.1f}" for cat, val in week_avg.items()))

    # --- Диета ---
    try:
        profile = get_diet_profile(user_id)
    except Exception:
        profile = None
    if profile:
        today_cal = get_today_calories(user_id)
        goal = profile.get('daily_calories') or 0
        lines.append(f"Диета: цель {int(goal)} ккал/день, съедено сегодня {int(today_cal)} ккал.")
        food_log = get_today_food_log(user_id)
        if food_log:
            food_items = "; ".join(f"{meal}: {desc} ({int(cal)} ккал)" for meal, desc, cal in food_log)
            lines.append(f"Еда сегодня: {food_items}")
        last_weight = get_last_weight(user_id)
        if last_weight:
            lines.append(f"Последний зафиксированный вес: {last_weight} кг")
    else:
        lines.append("Диета: профиль питания ещё не настроен.")

    # --- Тренировки ---
    workouts = stats['workouts'] or {}
    lines.append(
        f"Тренировки в этом месяце: {workouts.get('current_count', 0)}/{workouts.get('monthly_goal', 0)}"
    )
    try:
        cursor = db.execute("""
            SELECT date, status, skip_reason FROM ai_workout_sessions
            WHERE user_id = ? AND status != 'pending'
            ORDER BY date DESC LIMIT 5
        """, (user_id,))
        recent_sessions = cursor.fetchall()
    except Exception:
        recent_sessions = []
    if recent_sessions:
        sess_lines = []
        for date, status, skip_reason in recent_sessions:
            if status == 'done':
                sess_lines.append(f"{date}: выполнена")
            elif status == 'skipped':
                reason = f" ({skip_reason})" if skip_reason else ""
                sess_lines.append(f"{date}: пропущена{reason}")
            else:
                sess_lines.append(f"{date}: {status}")
        lines.append("Последние тренировки: " + "; ".join(sess_lines))

    # --- Задачи ---
    try:
        tasks = get_tasks_for_today(user_id)
    except Exception:
        tasks = []
    if tasks:
        task_lines = []
        for t in tasks:
            mark = "🔥" if t.get('is_priority') else "-"
            done = " ✅" if t.get('is_done') else ""
            task_lines.append(f"{mark} {t['title']}{done}")
        lines.append("Задачи на сегодня: " + "; ".join(task_lines))

    return "\n".join(lines)



def _parse_json_response(text: str) -> Optional[dict]:
    """Надёжно извлекает JSON из ответа Gemini."""
    if not text:
        return None

    # Проверяем на явные ошибки
    if text.startswith("❌") or text.startswith("Error"):
        print(f"[JSON] Explicit error in response: {repr(text[:100])}")
        return None

    clean = text.strip()

    # Сначала пробуем найти JSON в markdown code block
    if "```" in clean:
        # Ищем блок ```json ... ``` или ``` ... ```
        match = re.search(r'```\s*(?:json)?\s*\n?(.*?)```', clean, re.DOTALL)
        if match:
            clean = match.group(1).strip()
        else:
            # Если не нашли парный блок, просто убираем все ```
            clean = clean.replace("```", "").strip()

    # Берём от первой { до последней } - это надёжный способ вырезать JSON
    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1:
        print(f"[JSON] No braces found in: {repr(clean[:200])}")
        return None

    # Проверяем что { идёт перед }
    if start > end:
        print(f"[JSON] Invalid brace order: start={start}, end={end}")
        return None

    clean = clean[start:end+1]

    # Если JSON пустой или слишком короткий
    if len(clean) < 2:
        print(f"[JSON] Too short: {repr(clean)}")
        return None

    # Пытаемся распарсить
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"[JSON] Parse error: {e} | text: {repr(clean[:300])}")
        
        # Пробуем исправить частые проблемы
        # 1. Удаляем trailing commas
        clean_fixed = re.sub(r',\s*}', '}', clean)
        clean_fixed = re.sub(r',\s*]', ']', clean_fixed)
        try:
            result = json.loads(clean_fixed)
            print(f"[JSON] Fixed with trailing comma removal")
            return result
        except:
            pass
        
        # 2. Пробуем заменить одинарные кавычки на двойные
        try:
            clean_fixed = clean.replace("'", '"')
            result = json.loads(clean_fixed)
            print(f"[JSON] Fixed with single quote replacement")
            return result
        except:
            pass
        
        return None



def gemini_generate_plan(goal: str, level: str, days_per_week: int, notes: str = '') -> Optional[dict]:
    """Генерирует план тренировок через Gemini, возвращает dict."""
    day_keys = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    # Выбираем нужные дни равномерно
    selected = day_keys[:days_per_week]
    days_example = {}
    for d in selected:
        days_example[d] = [
            {"exercise": "Упражнение 1", "sets": 3, "reps": "10", "weight": 50},
            {"exercise": "Упражнение 2", "sets": 3, "reps": "12", "weight": None}
        ]
    example = json.dumps({"cycle_weeks": 1, "week_1": days_example}, ensure_ascii=False, indent=2)

    prompt = (
        f"Ты фитнес-тренер. Создай план тренировок.\n"
        f"Цель: {goal}\nУровень: {level}\nТренировок в неделю: {days_per_week}\n\n"
        f"Верни ТОЛЬКО валидный JSON строго в этом формате (замени упражнения на реальные):\n"
        f"{example}\n\n"
        f"Правила:\n"
        f"- Используй ровно {days_per_week} дней из: monday tuesday wednesday thursday friday saturday sunday\n"
        f"- sets — целое число, reps — строка, weight — число или null\n"
        f"- Если нужны чередующиеся недели добавь week_2 и обнови cycle_weeks\n"
        f"- ТОЛЬКО JSON, никакого текста до или после\n"
        + (f"- Учти пожелания пользователя: {notes}\n" if notes else "")
    )

    result = gemini_generate_json(prompt, max_tokens=8192)
    print(f"[AI PLAN] Raw ({len(result)} chars): {repr(result[:300])}")
    return _parse_json_response(result)



def _fallback_parse_plan(raw_text: str) -> Optional[dict]:
    """Запасной разбор плана — максимально либеральный."""
    print(f"[FALLBACK] Parsing: {repr(raw_text[:200])}")
    prompt = (
        "Разбери этот план тренировок в JSON. Даже если формат нестандартный — сделай максимум.\n\n"
        "Структура: {\"cycle_weeks\": N, \"week_1\": {\"monday\": [...], ...}}\n"
        "Каждое упражнение: {\"exercise\": \"название\", \"sets\": 3, \"reps\": \"10\", \"weight\": 80}\n\n"
        "Правила:\n"
        "- Блоки 'Неделя 1/2/3' внутри дня → разные week_1/week_2/week_3, cycle_weeks = макс номер\n"
        "- '/' на отдельной строке = граница между неделями в рамках одного дня\n"
        "- Упражнения без метки недели → дублируй во все недели\n"
        "- МАХ(20кг) → максимальный вес на 1 повторение: sets:1, reps:'1', weight:20\n"
        "- '50 повторений' → sets:1, reps:'50', weight:null\n"
        "- '40 минут' → sets:1, reps:'40 мин', weight:null\n"
        "- Дроп-сет '2x(60-40)' → sets:2, reps:'до отказа', weight:60\n"
        "Только JSON:\n\n"
        f"{raw_text}"
    )
    result = gemini_generate_json(prompt, max_tokens=8192)
    print(f"[FALLBACK] Raw response: {repr(result[:500])}")
    parsed = _parse_json_response(result)
    if parsed:
        print(f"[FALLBACK] Success: cycle_weeks={parsed.get('cycle_weeks')}")
    else:
        print(f"[FALLBACK] Failed to parse")
    return parsed



def gemini_parse_manual_plan(raw_text: str) -> Optional[dict]:
    """Парсит ручной план пользователя через Gemini."""
    prompt = (
        "Ты — парсер планов тренировок. Разбери текст и верни ТОЛЬКО валидный JSON, без пояснений.\n\n"

        "=== СТРУКТУРА ВЫВОДА ===\n"
        "{\n"
        '  "cycle_weeks": N,\n'
        '  "week_1": { "monday": [...], "wednesday": [...], ... },\n'
        '  "week_2": { ... },\n'
        '  "week_3": { ... }\n'
        "}\n\n"
        "Каждое упражнение:\n"
        '{ "exercise": "название", "sets": 3, "reps": "5", "weight": 100 }\n\n'

        "=== ПРАВИЛА ЧЕРЕДОВАНИЯ ===\n"
        "Если внутри одного дня есть строки вида 'Неделя 1 - ...', 'Неделя 2 - ...' — это чередование.\n"
        "Каждый блок 'Неделя N' относится только к week_N этого дня.\n"
        "Строки БЕЗ метки 'Неделя N' (до первого блока или после последнего) — дублируй во ВСЕ недели этого дня.\n"
        "cycle_weeks = максимальный номер недели в тексте. Если меток нет — cycle_weeks:1.\n\n"

        "=== ФОРМАТЫ УПРАЖНЕНИЙ ===\n"
        "3x5(110кг)           → sets:3, reps:'5', weight:110\n"
        "3х11(90кг)           → sets:3, reps:'11', weight:90  (х — русская буква, то же что x)\n"
        "МАХ(120кг)           → sets:1, reps:'1', weight:120  (максимальный вес на 1 повторение)\n"
        "МАХ повторений(20кг) → sets:1, reps:'MAX', weight:20\n"
        "50 повторений        → sets:1, reps:'50', weight:null\n"
        "2x(от 60кг к 50кг)  → sets:2, reps:'до отказа', weight:60\n"
        "40 минут             → sets:1, reps:'40 мин', weight:null\n"
        "BIU / навык / skill  → sets:1, reps:'1', weight:null\n"
        "Без веса             → weight:null\n\n"

        "=== ДНИ НЕДЕЛИ ===\n"
        "Понедельник→monday, Вторник→tuesday, Среда→wednesday, Четверг→thursday,\n"
        "Пятница→friday, Суббота→saturday, Воскресенье→sunday\n"
        "Пометки типа 'PUSH', 'PULL', 'LEG' после названия дня — игнорируй.\n\n"

        "=== ПРИМЕР (3-недельный цикл) ===\n"
        "Вход:\n"
        "Понедельник:\n"
        "Неделя 1 - Жим лёжа - МАХ(120кг)\n"
        "Неделя 2 - Жим лёжа - 3x5(110кг)\n"
        "Неделя 3 - Жим на наклонной - 3x11(90кг)\n"
        "Разгибания трицепса - 3x12(40кг)\n\n"
        "→ 'Разгибания трицепса' идёт без метки недели — дублируется в week_1, week_2, week_3.\n\n"
        "Выход:\n"
        "{\n"
        '  "cycle_weeks": 3,\n'
        '  "week_1": {"monday": [\n'
        '    {"exercise": "Жим лёжа", "sets": 1, "reps": "1", "weight": 120},\n'
        '    {"exercise": "Разгибания трицепса", "sets": 3, "reps": "12", "weight": 40}\n'
        '  ]},\n'
        '  "week_2": {"monday": [\n'
        '    {"exercise": "Жим лёжа", "sets": 3, "reps": "5", "weight": 110},\n'
        '    {"exercise": "Разгибания трицепса", "sets": 3, "reps": "12", "weight": 40}\n'
        '  ]},\n'
        '  "week_3": {"monday": [\n'
        '    {"exercise": "Жим на наклонной", "sets": 3, "reps": "11", "weight": 90},\n'
        '    {"exercise": "Разгибания трицепса", "sets": 3, "reps": "12", "weight": 40}\n'
        '  ]}\n'
        "}\n\n"

        "=== ТЕКСТ ПОЛЬЗОВАТЕЛЯ ===\n"
        f"{raw_text}\n\n"
        "Верни ТОЛЬКО JSON:"
    )

    result = gemini_generate_json(prompt, max_tokens=8192)
    print(f"[MANUAL PLAN] Raw ({len(result)} chars): {repr(result[:500])}")
    parsed = _parse_json_response(result)
    if parsed:
        print(f"[MANUAL PLAN] Parsed OK: cycle_weeks={parsed.get('cycle_weeks')}, weeks={[k for k in parsed if k.startswith('week')]}")
        if 'week_1' not in parsed:
            print(f"[MANUAL PLAN] WARNING: No week_1 found in parsed result!")
    else:
        print(f"[MANUAL PLAN] Parse FAILED - Raw full: {repr(result)}")
    return parsed



def gemini_edit_plan(current_plan: dict, edit_request: str) -> Optional[dict]:
    """Редактирует план через Gemini по запросу пользователя."""
    prompt = (
        f"Текущий план тренировок (JSON):\n{json.dumps(current_plan, ensure_ascii=False)}\n\n"
        f"Запрос пользователя: {edit_request}\n\n"
        f"Внеси изменения и верни ТОЛЬКО обновлённый JSON без markdown и пояснений."
    )
    result = gemini_generate_json(prompt, max_tokens=8192)
    return _parse_json_response(result)



def gemini_parse_exercise_result(exercise: dict, raw_text: str) -> dict:
    """Разбирает текстовый ответ пользователя по одному упражнению."""
    name = exercise.get("exercise", exercise.get("name", "упражнение"))
    prompt = f"""Упражнение: {name}
План: {exercise.get("sets")} подходов × {exercise.get("reps")} повторений, вес {exercise.get("weight")} кг

Пользователь написал: "{raw_text}"

Верни ТОЛЬКО JSON:
{{
  "sets_done": 3,
  "reps_done": "10",
  "weight_done": 60,
  "completed": true,
  "note": "не добил последний подход"
}}

Правила:
- completed: true если выполнил хотя бы частично
- note: короткая заметка только если есть что-то важное, иначе null
- Только JSON"""

    result = gemini_generate(prompt, max_tokens=256, raw=True)
    try:
        clean = result.strip()
        if clean.startswith("```"):
            clean = re.sub(r"```[a-z]*\n?", "", clean).replace("```", "").strip()
        if not clean.startswith(("{","[")) and ("{" in clean or "[" in clean):
            for start in ("{","["):
                if start in clean:
                    end = "}" if start == "{" else "]"
                    if end in clean:
                        clean = clean[clean.index(start):clean.rindex(end)+1]
                        break
        return json.loads(clean)
    except:
        return {"sets_done": None, "reps_done": None, "weight_done": None,
                "completed": True, "note": raw_text[:100]}



def gemini_session_feedback(session_logs: list, plan_exercises: list) -> str:
    """Генерирует краткий фидбек по завершённой тренировке."""
    done = [l for l in session_logs if l["status"] == "done"]
    skipped = [l for l in session_logs if l["status"] == "skipped"]
    done_results = [l.get("result") if isinstance(l, dict) else None for l in done]
    skipped_names = [l["exercise_name"] for l in skipped]
    plan_json = json.dumps(plan_exercises, ensure_ascii=False)
    done_json = json.dumps(done_results, ensure_ascii=False)
    skipped_str = str(skipped_names)
    prompt = (
        "Пользователь завершил тренировку.\n"
        f"План: {plan_json}\n"
        f"Выполнено: {done_json}\n"
        f"Пропущено: {skipped_str}\n\n"
        "Напиши КРАТКИЙ фидбек (2-3 предложения). "
        "Только если есть прогресс — отметь. Если что-то пропущено — упомяни. Без воды."
    )
    return gemini_generate(prompt, max_tokens=300)



def gemini_adapt_next_session(plan_exercises: list, session_logs: list,
                               prev_sessions: list) -> list:
    """Адаптирует план следующей такой же тренировки на основе результатов."""
    logs_summary = [
        {
            "exercise": l["exercise_name"],
            "result": l.get("result"),
            "status": l["status"]
        }
        for l in session_logs
    ]
    plan_json = json.dumps(plan_exercises, ensure_ascii=False)
    logs_json = json.dumps(logs_summary, ensure_ascii=False)
    prompt = (
        "Ты тренер. Адаптируй план следующей тренировки на основе результатов.\n\n"
        f"Текущий план:\n{plan_json}\n\n"
        f"Результаты сегодня:\n{logs_json}\n\n"
        "Верни ТОЛЬКО JSON — обновлённый список упражнений (та же структура).\n"
        "Меняй только sets/reps/weight. Упражнения не меняй. Только JSON."
    )
    result = gemini_generate(prompt, max_tokens=1024, raw=True)
    parsed = _parse_json_response(result)
    if isinstance(parsed, list):
        return parsed
    # Если вернул dict с вложенным списком
    if isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, list):
                return v
    return plan_exercises



def gemini_monthly_review(plan: dict, recent_sessions: list) -> Optional[dict]:
    """Предлагает замену упражнений раз в месяц."""
    prompt = f"""Ты тренер. Проанализируй план тренировок и последние результаты.

Текущий план:
{json.dumps(plan, ensure_ascii=False)}

Последние тренировки (краткие результаты):
{json.dumps(recent_sessions[:10], ensure_ascii=False)}

Предложи замены упражнений если нужно. Верни ТОЛЬКО JSON:
{{
  "changes": [
    {{"day": "monday", "week": "week_1", "old_exercise": "Жим лёжа", "new_exercise": "Жим гантелей", "reason": "для разнообразия и проработки стабилизаторов"}},
  ],
  "no_changes_needed": false
}}

Если менять ничего не нужно — верни {{"changes": [], "no_changes_needed": true}}.
Только JSON."""

    result = gemini_generate(prompt, max_tokens=1024)
    try:
        clean = result.strip()
        if clean.startswith("```"):
            clean = re.sub(r"```[a-z]*\n?", "", clean).replace("```", "").strip()
        return json.loads(clean)
    except:
        return None



def generate_proactive_ai_message(user_id: int) -> str:
    stats = get_user_stats_for_ai(user_id)
    name = get_user_name(user_id)
    yesterday = stats['yesterday']
    today = stats['today']

    prompt = f"""Пользователь {name}. Вчерашние данные: {yesterday}. Сегодня уже оценил: {today}.
    Составь короткое персональное приветствие-вопрос (макс 2 предложения) на основе вчерашних данных.
    Если вчера что-то было плохо (оценка <=4), спроси как сегодня.
    Если всё было хорошо, похвали и спроси что оценим сегодня.
    Обращайся по имени."""
    return gemini_generate(prompt, max_tokens=1024)



def analyze_low_rating(user_id: int, category: str, rating: int) -> str:
    name = get_user_name(user_id)
    stats = get_user_stats_for_ai(user_id)
    prompt = f"""Пользователь {name} поставил {category} {rating}/10. 
    Его статистика за неделю: {stats['week_avg']}. 
    Дай 1 конкретный совет что могло пойти не так и как улучшить. Макс 2 предложения. Обращайся по имени."""
    return gemini_generate(prompt, max_tokens=1024)



def generate_weekly_report(user_id: int) -> str:
    stats = get_user_stats_for_ai(user_id)
    name = get_user_name(user_id)
    daily_data = get_daily_ratings(user_id, days=7)

    day_scores = {}
    for date, cat, rating in daily_data:
        if date not in day_scores:
            day_scores[date] = []
        day_scores[date].append(rating)

    avg_by_day = {date: sum(ratings)/len(ratings) for date, ratings in day_scores.items() if ratings}

    best_day = max(avg_by_day, key=avg_by_day.get) if avg_by_day else None
    worst_day = min(avg_by_day, key=avg_by_day.get) if avg_by_day else None

    workout_data = stats['workouts']

    prompt = f"""Составь разбор недели для {name}:
    Лучший день: {best_day} (средняя {avg_by_day.get(best_day, 0):.1f})
    Худший день: {worst_day} (средняя {avg_by_day.get(worst_day, 0):.1f})
    Тренировок: {workout_data['current_count']}/{workout_data['monthly_goal']}
    Средние за неделю: {stats['week_avg']}

    Напиши:
    1. Краткий анализ лучшего дня (что было хорошо)
    2. Краткий анализ худшего дня (что пошло не так)
    3. Паттерн если виден (связь сна и активности и т.д.)
    4. Мотивирующий совет на следующую неделю

    Используй эмодзи, обращайся по имени, макс 5-6 предложений."""
    ai_analysis = gemini_generate(prompt, max_tokens=2048)

    best_day_str = f"{best_day[8:10]}.{best_day[5:7]}" if best_day else '--'
    worst_day_str = f"{worst_day[8:10]}.{worst_day[5:7]}" if worst_day else '--'

    report = f"""┌─ Разбор недели | {name}
│
│ 📈 Лучший день: {best_day_str}
│    Средняя оценка: {avg_by_day.get(best_day, 0):.1f}/10
│
│ 📉 Худший день: {worst_day_str}
│    Средняя оценка: {avg_by_day.get(worst_day, 0):.1f}/10
│
│ 🏋️ Тренировок: {workout_data['current_count']}/{workout_data['monthly_goal']}
│
│ 🤖 Анализ ИИ:
│    {ai_analysis}
└─────────────────────"""
    return report
