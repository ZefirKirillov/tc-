"""Tests for the health-check HTTP endpoint.

Stdlib-only: `aiohttp` is stubbed so these tests run without Telegram,
Turso, Gemini, or internet access.
"""
import asyncio
import json
import os
import sys
import types
import unittest


def _stub_aiohttp():
    mod = types.ModuleType("aiohttp")
    web = types.ModuleType("aiohttp.web")

    class Application:
        def __init__(self):
            self.router = Router()

    class Router:
        def __init__(self):
            self.routes = {}

        def add_get(self, path, handler):
            self.routes[path] = handler

    class FakeResponse:
        def __init__(self, status=200, body=b"", content_type="text/plain"):
            self.status = status
            self.body = body
            self.content_type = content_type

        @property
        def text(self):
            return self.body.decode("utf-8")

    def json_response(data):
        return FakeResponse(status=200, body=json.dumps(data).encode("utf-8"),
                            content_type="application/json")

    class Response(FakeResponse):
        def __init__(self, text=""):
            super().__init__(status=200, body=text.encode("utf-8"),
                             content_type="text/plain")

    started = {}

    class AppRunner:
        def __init__(self, app):
            self.app = app
            self.cleaned_up = False

        async def setup(self):
            pass

        async def cleanup(self):
            self.cleaned_up = True

    class TCPSite:
        def __init__(self, runner, host, port):
            started["host"] = host
            started["port"] = port
            started["runner"] = runner

        async def start(self):
            started["started"] = True

    web.Application = Application
    web.json_response = json_response
    web.Response = Response
    web.AppRunner = AppRunner
    web.TCPSite = TCPSite
    mod.web = web
    sys.modules["aiohttp"] = mod
    sys.modules["aiohttp.web"] = web
    return started


_STARTED = _stub_aiohttp()
sys.path.insert(0, ".")


class TestHealthEndpoints(unittest.TestCase):
    def test_healthz_returns_200_and_exact_body(self):
        from trackcheck.health import healthz
        resp = asyncio.run(healthz(None))
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(resp.body.decode("utf-8")), {"status": "ok"})
        self.assertEqual(resp.body.decode("utf-8"), '{"status": "ok"}')

    def test_index_returns_200(self):
        from trackcheck.health import index
        resp = asyncio.run(index(None))
        self.assertEqual(resp.status, 200)
        self.assertIn("TrackCheck", resp.text)

    def test_port_read_from_environment(self):
        from trackcheck.health import get_port
        old = os.environ.get("PORT")
        try:
            os.environ["PORT"] = "12345"
            self.assertEqual(get_port(), 12345)
            del os.environ["PORT"]
            self.assertEqual(get_port(), 10000)
        finally:
            if old is not None:
                os.environ["PORT"] = old
            elif "PORT" in os.environ:
                del os.environ["PORT"]

    def test_server_binds_to_all_interfaces(self):
        from trackcheck.health import HOST, start_health_server
        self.assertEqual(HOST, "0.0.0.0")
        old = os.environ.get("PORT")
        try:
            os.environ["PORT"] = "15555"
            asyncio.run(start_health_server())
            self.assertTrue(_STARTED.get("started"))
            self.assertEqual(_STARTED.get("host"), "0.0.0.0")
            self.assertEqual(_STARTED.get("port"), 15555)
        finally:
            if old is not None:
                os.environ["PORT"] = old
            elif "PORT" in os.environ:
                del os.environ["PORT"]

    def test_no_self_ping(self):
        for path in ("trackcheck/health.py", "trackcheck/app.py"):
            with open(path, encoding="utf-8") as f:
                src = f.read().lower()
        self.assertNotIn("onrender.com", src)
        self.assertNotIn("self-ping", src)
        self.assertNotIn("self_ping", src)


if __name__ == "__main__":
    unittest.main()
