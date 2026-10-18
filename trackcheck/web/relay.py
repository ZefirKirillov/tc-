"""Relay for the serverless bot (see serverless/).

The Telegram-hosted bot runs JavaScript with a ~30 s limit per update and can't
reach GigaChat (port 9443 and the Russian root CA are refused there), so AI
calls and chart rendering stay here:

  POST /relay/generate  — one AI call through ai_service._generate_text (or its
                          streaming variant). Answers as NDJSON: {"tick": n}
                          every 2 s, {"delta": "..."} while streaming, then
                          {"done": true, "text": ..., "error": ...}. After
                          `wait` seconds it answers {"pending": true} instead
                          and keeps working; the same `key` later joins the job.
  POST /relay/chart     — PNG of one of the bot's plotly charts.

Both require the X-Relay-Secret header to equal RELAY_SECRET.
"""
import asyncio
import base64
import hmac
import io
import json
import os
import threading
import time

from aiohttp import web

RELAY_SECRET = os.getenv("RELAY_SECRET", "")
JOB_TTL_SEC = 15 * 60
MAX_WAIT_SEC = 25.0
PHOTO_MAX_SIDE = 1600

_jobs: dict = {}
_jobs_lock = threading.Lock()


class _Job:
    def __init__(self):
        self.pieces: list = []
        self.text = None
        self.error = None
        self.done = threading.Event()
        self.created = time.monotonic()


def _authorized(request: web.Request) -> bool:
    got = request.headers.get("X-Relay-Secret", "")
    return bool(RELAY_SECRET) and hmac.compare_digest(got, RELAY_SECRET)


def _normalize_image(image_bytes: bytes) -> bytes:
    """Downscale + JPEG, as the Mini App upload path did (full-size phone photos
    are too big for the AI routers). exif_transpose keeps portrait shots upright."""
    from PIL import Image, ImageOps
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
    image.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _run_job(job: _Job, req: dict, image_bytes):
    from trackcheck.services import ai_service as ai
    try:
        prompt = req["prompt"]
        max_tokens = int(req.get("max_tokens") or 8192)
        if not ai._has_any_key(ratings=bool(req.get("rating_key")), image=bool(image_bytes)):
            job.error = "❌ ИИ недоступен (нет API-ключа). Установи ATRIA_API_KEY или NARA_API."
            return
        if req.get("stream") and not image_bytes:
            for piece in ai.gemini_generate_stream(prompt, max_tokens):
                job.pieces.append(piece)
            text = "".join(job.pieces)
        else:
            text = ai._generate_text(prompt, max_tokens, image_bytes=image_bytes,
                                     think_off=bool(req.get("think_off")),
                                     rating_key=bool(req.get("rating_key")))
        if text and text.strip():
            job.text = text
        else:
            job.error = ai._friendly_ai_error()
    except Exception as e:
        import traceback
        traceback.print_exc()
        job.error = f"❌ Ошибка ИИ: {str(e)[:100]}"
    finally:
        job.done.set()


def _sweep():
    now = time.monotonic()
    with _jobs_lock:
        for key in [k for k, j in _jobs.items() if now - j.created > JOB_TTL_SEC]:
            del _jobs[key]


async def relay_generate(request: web.Request):
    if not _authorized(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        req = await request.json()
        key = str(req["key"])[:128]
        assert isinstance(req.get("prompt"), str) and req["prompt"]
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    _sweep()
    with _jobs_lock:
        job = _jobs.get(key)
        fresh = job is None
        if fresh:
            job = _jobs[key] = _Job()
    if fresh:
        image_bytes = None
        if req.get("image_b64"):
            try:
                image_bytes = _normalize_image(base64.b64decode(req["image_b64"]))
            except Exception:
                job.error = "❌ Не получилось прочитать фото."
                job.done.set()
        if not job.done.is_set():
            threading.Thread(target=_run_job, args=(job, req, image_bytes), daemon=True).start()

    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson"})
    await resp.prepare(request)

    async def emit(obj):
        await resp.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))

    wait = min(float(req.get("wait") or MAX_WAIT_SEC), MAX_WAIT_SEC)
    started = time.monotonic()
    sent, tick, next_tick = 0, 0, started + 2
    try:
        while True:
            while sent < len(job.pieces):
                await emit({"delta": job.pieces[sent]})
                sent += 1
            if job.done.is_set():
                await emit({"done": True, "text": job.text, "error": job.error})
                with _jobs_lock:
                    if _jobs.get(key) is job:
                        del _jobs[key]  # delivered
                break
            now = time.monotonic()
            if now - started >= wait:
                await emit({"pending": True})
                break
            if now >= next_tick:
                tick += 1
                next_tick += 2
                await emit({"tick": tick})
            await asyncio.sleep(0.2)
    except (ConnectionResetError, asyncio.CancelledError):
        pass  # client gave up; the job stays for a retry with the same key
    await resp.write_eof()
    return resp


async def relay_chart(request: web.Request):
    """{kind: 'reflection' (user_id, days) | 'diet' (user_id) | 'workout' (user_id, rows, ex_type)}"""
    if not _authorized(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        req = await request.json()
        kind = req["kind"]
        user_id = int(req["user_id"])
    except Exception:
        return web.json_response({"ok": False, "error": "bad_json"}, status=400)
    from trackcheck.utils.concurrency import run_db

    def build():
        if kind == "reflection":
            from trackcheck.database.repositories import get_daily_ratings
            from trackcheck.services.stats_service import create_line_chart
            days = int(req.get("days") or 7)
            data = get_daily_ratings(user_id, days=days)
            return create_line_chart(data, user_id, days=days) if data else None
        if kind == "diet":
            from trackcheck.database.connection import db
            from trackcheck.services.chart_service import build_diet_chart
            w = db.execute("SELECT date, weight FROM weight_log WHERE user_id = ? ORDER BY date",
                           (user_id,)).fetchall()
            f = db.execute("SELECT date, body_fat FROM body_fat_log WHERE user_id = ? ORDER BY date",
                           (user_id,)).fetchall()
            return build_diet_chart(user_id, w, f)
        if kind == "workout":
            from trackcheck.services.chart_service import build_workout_progress_chart
            return build_workout_progress_chart(user_id, req["rows"], req.get("ex_type") or "strength")
        raise ValueError(kind)

    try:
        path = await run_db(build)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"ok": False, "error": f"chart_failed: {e}"}, status=500)
    if not path:
        return web.json_response({"ok": False, "error": "no_data"}, status=404)
    try:
        with open(path, "rb") as fh:
            png = fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return web.Response(body=png, content_type="image/png")


def register_relay_routes(app: web.Application):
    app.router.add_post("/relay/generate", relay_generate)
    app.router.add_post("/relay/chart", relay_chart)
