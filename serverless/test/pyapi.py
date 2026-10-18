"""Run a list of Mini App API calls against the Python aiohttp API; print the responses."""
import asyncio, json, os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.update(DB_PATH=_db.name, BOT_TOKEN="1:TEST", TURSO_DATABASE_URL="", TURSO_AUTH_TOKEN="", ACTION_LOG_ENABLED="0", DB_SLOW_MS="0")
_OUT = sys.stdout
sys.stdout = sys.stderr
from aiohttp.test_utils import TestServer, TestClient  # noqa: E402
CALLS = json.load(open(sys.argv[1]))
USER = {"id": 42, "first_name": "Тест", "username": "tester"}

async def main():
    from trackcheck.database.connection import init_db, db
    init_db()
    db.execute("INSERT INTO user_settings (user_id, username, first_name, timezone) VALUES (42, 'tester', 'Тест', 'Europe/Moscow')")
    import trackcheck.web.auth as auth
    import trackcheck.web.api as api
    api.validate_init_data = auth.validate_init_data = lambda *a, **k: USER
    from trackcheck.services import ai_service as ai
    state = {"reply": "ok"}
    ai._has_any_key = lambda ratings=False, image=False: True
    ai._generate_text = lambda prompt, *a, **k: state["reply"]
    client = TestClient(TestServer(api.create_api_app()))
    await client.start_server()
    out = []
    for c in CALLS:
        if "ai" in c:
            state["reply"] = c["ai"]
        if "path" not in c:
            continue
        kw = {}
        if "photo" in c:
            import io
            from PIL import Image
            from aiohttp import FormData
            buf = io.BytesIO(); Image.new("RGB", (4, 4)).save(buf, format="JPEG")
            fd = FormData(); fd.add_field("photo", buf.getvalue(), filename="p.jpg", content_type="image/jpeg")
            kw["data"] = fd
        elif c.get("body") is not None:
            kw["json"] = c["body"]
        r = await client.request(c["method"], c["path"], headers={"X-Telegram-Init-Data": "x"}, **kw)
        out.append({"call": c, "status": r.status, "body": await r.json()})
    await client.close()
    _OUT.write(json.dumps(out, ensure_ascii=False))

asyncio.run(main())
