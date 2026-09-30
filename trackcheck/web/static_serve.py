"""Static serving for the React Mini App build.

Vite build output lives in trackcheck/web/static/ (committed after
`npm run build` inside miniapp/). Served under /app with SPA fallback:
any /app/* path returns index.html so client-side routing works.
"""
import pathlib

from aiohttp import web

STATIC_DIR = pathlib.Path(__file__).parent / "static"
APP_PREFIX = "/app"


async def _serve_index(request: web.Request):
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return web.Response(
            text="Mini App frontend not built yet. Run: cd miniapp && npm ci && npm run build",
            status=503,
        )
    return web.FileResponse(index)


def register_static(app: web.Application):
    if STATIC_DIR.exists():
        app.router.add_static(f"{APP_PREFIX}/assets", STATIC_DIR / "assets", show_index=False)
        # Vite root files (favicon, etc.) if present
        for fname in ("favicon.ico", "manifest.json", "icon.svg"):
            fpath = STATIC_DIR / fname
            if fpath.exists():
                app.router.add_get(f"{APP_PREFIX}/{fname}", lambda r, p=fpath: web.FileResponse(p))

    # SPA fallback must come AFTER /api/* routes are registered.
    app.router.add_get(APP_PREFIX, _serve_index)
    app.router.add_get(f"{APP_PREFIX}/{{tail:.*}}", _serve_index)
