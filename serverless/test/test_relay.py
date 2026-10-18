"""Relay for the serverless bot (trackcheck/web/relay.py). Needs the bot's Python deps:
    python -m pytest serverless/test/test_relay.py
"""
import asyncio
import json
import os
import sys
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
os.environ.setdefault("RELAY_SECRET", "s3cret")

from trackcheck.web import relay  # noqa: E402


def _lines(text):
    return [json.loads(l) for l in text.splitlines() if l.strip()]


@pytest.fixture
def patched(monkeypatch):
    from trackcheck.services import ai_service as ai
    calls = {"n": 0, "delay": 0.0, "reply": "готово"}

    def gen(prompt, max_tokens=8192, image_bytes=None, think_off=False, rating_key=False, caller=None):
        calls["n"] += 1
        time.sleep(calls["delay"])
        return calls["reply"]

    def stream(prompt, max_tokens=8192, caller="x"):
        calls["n"] += 1
        for piece in ("гото", "во"):
            time.sleep(calls["delay"] / 2)
            yield piece

    monkeypatch.setattr(relay, "RELAY_SECRET", "s3cret")
    monkeypatch.setattr(ai, "_has_any_key", lambda ratings=False, image=False: True)
    monkeypatch.setattr(ai, "_generate_text", gen)
    monkeypatch.setattr(ai, "gemini_generate_stream", stream)
    relay._jobs.clear()
    return calls


async def _client():
    app = web.Application()
    relay.register_relay_routes(app)
    c = TestClient(TestServer(app))
    await c.start_server()
    return c


def _post(c, body, secret="s3cret"):
    return c.post("/relay/generate", json=body, headers={"X-Relay-Secret": secret})


def test_requires_secret(patched):
    async def run():
        c = await _client()
        r = await _post(c, {"key": "k", "prompt": "p"}, secret="nope")
        assert r.status == 401
        await c.close()
    asyncio.run(run())


def test_fast_answer_is_delivered_and_forgotten(patched):
    async def run():
        c = await _client()
        r = await _post(c, {"key": "k1", "prompt": "p", "wait": 5})
        assert _lines(await r.text())[-1] == {"done": True, "text": "готово", "error": None}
        assert "k1" not in relay._jobs
        await c.close()
    asyncio.run(run())


def test_slow_answer_goes_pending_and_retry_joins_the_same_job(patched):
    patched["delay"] = 1.5

    async def run():
        c = await _client()
        r = await _post(c, {"key": "k2", "prompt": "p", "wait": 0.5})
        assert _lines(await r.text())[-1] == {"pending": True}
        r = await _post(c, {"key": "k2", "prompt": "p", "wait": 5})
        assert _lines(await r.text())[-1]["text"] == "готово"
        assert patched["n"] == 1, "the retry must not start a second AI call"
        await c.close()
    asyncio.run(run())


def test_heartbeat_and_stream_deltas(patched):
    patched["delay"] = 2.4

    async def run():
        c = await _client()
        r = await _post(c, {"key": "k3", "prompt": "p", "wait": 5, "stream": True})
        ev = _lines(await r.text())
        assert {"tick": 1} in ev
        assert [e["delta"] for e in ev if "delta" in e] == ["гото", "во"]
        assert ev[-1]["text"] == "готово"
        await c.close()
    asyncio.run(run())


def test_ai_failure_reports_friendly_error(patched):
    patched["reply"] = None

    async def run():
        c = await _client()
        r = await _post(c, {"key": "k4", "prompt": "p", "wait": 5})
        last = _lines(await r.text())[-1]
        assert last["done"] and last["text"] is None and last["error"].startswith("❌")
        await c.close()
    asyncio.run(run())


def test_photo_is_downscaled_to_jpeg(patched, monkeypatch):
    import base64
    import io
    from PIL import Image
    from trackcheck.services import ai_service as ai
    seen = {}

    def gen(prompt, max_tokens=8192, image_bytes=None, **kw):
        seen["img"] = image_bytes
        return "суп 300 10 10 30"
    monkeypatch.setattr(ai, "_generate_text", gen)
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), "red").save(buf, format="PNG")

    async def run():
        c = await _client()
        r = await _post(c, {"key": "k5", "prompt": "p", "wait": 10,
                            "image_b64": base64.b64encode(buf.getvalue()).decode()})
        assert _lines(await r.text())[-1]["text"].startswith("суп")
        img = Image.open(io.BytesIO(seen["img"]))
        assert img.format == "JPEG" and max(img.size) == 1600
        await c.close()
    asyncio.run(run())


def test_chart(patched, monkeypatch, tmp_path):
    import trackcheck.services.stats_service as st
    import trackcheck.database.repositories as repo
    png = tmp_path / "c.png"
    png.write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(repo, "get_daily_ratings", lambda uid, days=7: [("2026-10-18", "сон", 7)])
    monkeypatch.setattr(st, "create_line_chart", lambda data, uid, days=7: str(png))

    async def run():
        c = await _client()
        r = await c.post("/relay/chart", json={"kind": "reflection", "user_id": 42, "days": 7},
                         headers={"X-Relay-Secret": "s3cret"})
        assert r.status == 200 and (await r.read()).startswith(b"\x89PNG")
        await c.close()
    asyncio.run(run())
