"""Оценка тела по фото: балл 1–10, сильные и слабые места, что делать со слабыми.
Балл идёт в «реализованный потенциал» (см. potential_service) до следующего фото."""
from typing import Optional

BODY_SCORE_PROMPT = """Ты опытный тренер. Оцени телосложение человека на фото по шкале 1–10.
Шкала: 3 — заметный лишний вес или очень слабая мускулатура; 5 — обычное нетренированное тело;
7 — видно, что человек тренируется (тонус, пропорции, умеренный процент жира);
9–10 — уровень фитнес-модели или спортсмена. Оценивай честно, без лести и без жестокости.

Верни ТОЛЬКО JSON:
{"score": 6,
 "summary": "одно предложение — общее впечатление",
 "strengths": ["сильное место", "ещё одно"],
 "weaknesses": [{"spot": "слабое место", "fix": "что конкретно делать (упражнения, питание)"}]}

1–3 сильных места, 1–3 слабых. Коротко, на «ты».
Если на фото не видно тела человека — верни {"error": "no_body"}."""

NO_BODY = "no_body"


def parse_body_score(text: Optional[str]) -> Optional[dict]:
    """Ответ модели → {score, summary, strengths, weaknesses} | {"error": "no_body"} | None."""
    from trackcheck.services.ai_service import _parse_json_response
    data = _parse_json_response(text or "")
    if not isinstance(data, dict):
        return None
    if data.get("error") == NO_BODY:
        return {"error": NO_BODY}
    try:
        score = max(1, min(10, int(round(float(data.get("score"))))))
    except (TypeError, ValueError):
        return None
    strengths = [str(s).strip() for s in (data.get("strengths") or []) if str(s).strip()][:3]
    weaknesses = []
    for w in (data.get("weaknesses") or [])[:3]:
        if isinstance(w, dict) and str(w.get("spot") or "").strip():
            weaknesses.append({"spot": str(w["spot"]).strip(), "fix": str(w.get("fix") or "").strip()})
        elif isinstance(w, str) and w.strip():
            weaknesses.append({"spot": w.strip(), "fix": ""})
    return {"score": score, "summary": str(data.get("summary") or "").strip(),
            "strengths": strengths, "weaknesses": weaknesses}


def rate_body_photo(image_bytes: bytes) -> Optional[dict]:
    """ИИ-оценка фото (медленно — вызывать в потоке). None — ИИ не ответил."""
    from trackcheck.services.ai_service import analyze_body_photo
    return parse_body_score(analyze_body_photo(image_bytes, BODY_SCORE_PROMPT, max_tokens=2048))


def format_body_score(result: dict) -> str:
    """Текст для бота."""
    lines = [f"💪 Оценка тела: {result['score']}/10"]
    if result.get("summary"):
        lines += ["", result["summary"]]
    if result.get("strengths"):
        lines += ["", "✅ Сильные стороны"] + [f"• {s}" for s in result["strengths"]]
    if result.get("weaknesses"):
        lines += ["", "🎯 Над чем работать"]
        lines += [f"• {w['spot']}" + (f" — {w['fix']}" if w.get("fix") else "") for w in result["weaknesses"]]
    lines += ["", "Оценка идёт в «реализованный потенциал» до следующего фото."]
    return "\n".join(lines)


def score_photo_for_bot(user_id: int, image_bytes: bytes) -> str:
    """Оценить, сохранить и вернуть текст для бота; при неудаче — строка с «❌»."""
    from trackcheck.database.repositories import save_body_score
    from trackcheck.services.ai_service import _friendly_ai_error
    result = rate_body_photo(image_bytes)
    if result is None:
        return _friendly_ai_error()
    if result.get("error") == NO_BODY:
        return "❌ На фото не видно тела. Пришли фото в полный рост или по пояс."
    save_body_score(user_id, result)
    return format_body_score(result)
