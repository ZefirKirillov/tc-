"""Run a scripted conversation through the original Python bot (aiogram) with a
fake Telegram connection, and print what the user would see, as JSON.

    python pyref.py scenario.json > out.json

The JS port is driven by the same scenario in jsref.mjs; compare.mjs diffs them.
"""
import asyncio
import datetime as _dt
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.update(DB_PATH=_db.name, BOT_TOKEN="1:TEST", TURSO_DATABASE_URL="", TURSO_AUTH_TOKEN="",
                  MINIAPP_BASE_URL="https://app123.tgcloud.ai", ACTION_LOG_ENABLED="0", DB_SLOW_MS="0")

import io  # noqa: E402

_OUT = sys.stdout
sys.stdout = sys.stderr  # the bot prints a lot; keep stdout for the JSON result

from PIL import Image  # noqa: E402
from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import Update  # noqa: E402

SCENARIO = json.load(open(sys.argv[1]))
STATE = {"next_id": 1000, "calls": [], "ai": None, "ai_calls": []}


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    return buf.getvalue()


def _clean(v):
    from aiogram.client.default import Default
    from aiogram.types import InputFile
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if not isinstance(x, Default)}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, InputFile):
        return "<file>"
    if hasattr(v, "model_dump"):
        return _clean(v.model_dump(exclude_none=True, by_alias=True, warnings=False))
    return v


class MockSession(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        name = method.__api_method__
        params = _clean(method.model_dump(exclude_none=True, by_alias=True, warnings=False))
        STATE["calls"].append({"method": name, "params": params})
        rt = method.__returning__
        if name in ("sendMessage", "sendPhoto"):
            mid = STATE["next_id"]
            STATE["next_id"] += 1
            STATE["calls"][-1]["sentId"] = mid
            return rt.model_validate({"message_id": mid, "date": 0, "chat": {"id": params.get("chat_id"), "type": "private"},
                                      "text": params.get("text")}, context={"bot": bot})
        if name == "editMessageText":
            from aiogram.types import Message
            return Message.model_validate({"message_id": params.get("message_id"), "date": 0,
                                           "chat": {"id": params.get("chat_id"), "type": "private"}, "text": params.get("text")},
                                          context={"bot": bot})
        if name == "getFile":
            return rt.model_validate({"file_id": params["file_id"], "file_unique_id": "u", "file_path": "photos/x.jpg"})
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield _png()

    async def close(self):
        pass


def _patch_ai():
    from trackcheck.services import ai_service as ai

    def reply(prompt, **kw):
        STATE["ai_calls"].append({"prompt": prompt, **kw})
        r = STATE["ai"](prompt) if STATE["ai"] else "ok"
        return None if r is None else str(r)

    ai._has_any_key = lambda ratings=False, image=False: True
    ai._generate_text = lambda prompt, max_tokens=8192, image_bytes=None, think_off=False, rating_key=False, caller=None: \
        reply(prompt, max_tokens=max_tokens, image=bool(image_bytes), think_off=think_off, rating_key=rating_key)

    def stream(prompt, max_tokens=8192, caller="x"):
        text = reply(prompt, max_tokens=max_tokens, stream=True)
        if text:
            yield text[:3]
            yield text[3:]
    ai.gemini_generate_stream = stream
    ai.LAST_AI_CALL.update(provider=None, model=None, reason="")


def _patch_charts():
    def fake(*a, **k):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.write(fd, _png())
        os.close(fd)
        return path
    import trackcheck.services.stats_service as st
    import trackcheck.services.chart_service as ch
    import trackcheck.handlers.stats as hs
    import trackcheck.handlers.food as hf
    import trackcheck.handlers.workouts as hw
    st.create_line_chart = ch.build_diet_chart = ch.build_workout_progress_chart = fake
    hs.create_line_chart = hf.build_diet_chart = hw.build_workout_progress_chart = fake


async def _no_sleep(*_a, **_k):
    await _real_sleep(0)

_real_sleep = asyncio.sleep


def _ai_script(spec):
    """A step's "ai": a string, or a list consumed in order."""
    if spec is None:
        return None
    if isinstance(spec, list):
        queue = list(spec)
        return lambda _p: queue.pop(0) if queue else "ok"
    return lambda _p: spec


async def main():
    from trackcheck.database.connection import init_db
    init_db()
    _patch_ai()
    _patch_charts()
    asyncio.sleep = _no_sleep
    from trackcheck.handlers import router
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    bot = Bot(token="1:TEST", session=MockSession())
    user = {"id": 42, "is_bot": False, "first_name": "Тест", "username": "tester"}
    chat = {"id": 42, "type": "private"}
    out = []
    for i, step in enumerate(SCENARIO["steps"]):
        if "ai" in step:
            STATE["ai"] = _ai_script(step["ai"])
        if "sql" in step:
            from trackcheck.database.connection import db
            for q in step["sql"]:
                db.execute(q)
            continue
        if not any(k in step for k in ("say", "photo", "press")):
            continue
        before = len(STATE["calls"])
        if "say" in step or "photo" in step:
            msg = {"message_id": STATE["next_id"], "from": user, "chat": chat, "date": 0}
            STATE["next_id"] += 1
            if "say" in step:
                msg["text"] = step["say"]
            else:
                msg["photo"] = [{"file_id": "small", "file_unique_id": "s", "width": 90, "height": 90},
                                {"file_id": step["photo"], "file_unique_id": "b", "width": 1280, "height": 960}]
            upd = {"update_id": i + 1, "message": msg}
        else:
            data = step["press"]
            mid = _last_with_button(data)
            upd = {"update_id": i + 1, "callback_query": {"id": str(i), "from": user, "chat_instance": "1", "data": data,
                                                          "message": {"message_id": mid or 1, "date": 1, "chat": chat}}}
        await dp.feed_update(bot, Update.model_validate(upd, context={"bot": bot}))
        # finish background tasks (delayed deletes, rating syncs)
        for _ in range(5):
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            if not pending:
                break
            await asyncio.gather(*pending, return_exceptions=True)
        out.append({"step": step, "calls": STATE["calls"][before:]})
    from trackcheck.database.connection import db
    dump = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        rows = db.execute(f"SELECT * FROM {name}").fetchall()
        dump[name] = [list(r) for r in rows]
    _OUT.write(json.dumps({"steps": out, "db": dump, "ai_calls": STATE["ai_calls"]}, ensure_ascii=False, default=str))


def _last_with_button(data):
    for c in reversed(STATE["calls"]):
        if c["method"] not in ("sendMessage", "editMessageText", "editMessageReplyMarkup"):
            continue
        rm = c["params"].get("reply_markup") or {}
        for row in rm.get("inline_keyboard") or []:
            for b in row:
                if b.get("callback_data") == data:
                    return c["params"].get("message_id") or c.get("sentId")
    return None


asyncio.run(main())
