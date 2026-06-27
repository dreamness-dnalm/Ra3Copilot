"""FastAPI application assembly for the daemon.

Mounts the runs router (Step 2) plus health/shutdown. Data-layer routers
(Step 3) are included there. CORS is permissive for localhost so a pywebview
``file://`` origin (and later Tauri/WPF) can call the API.
"""

from __future__ import annotations

import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.runtime_env import load_runtime_env
from daemon.api import protocol
from daemon.api import context as context_api
from daemon.api import files as files_api
from daemon.api import history as history_api
from daemon.api import projects as projects_api
from daemon.api import runs as runs_api
from daemon.api import settings as settings_api
from daemon.api import terminal as terminal_api
from daemon.api import usage as usage_api
from daemon.locking import HEALTH_PATH, clear_pidfile, get_or_create_token, write_pidfile
from daemon.qq_bot import qq_bot_service

_START_TIME = time.time()
_TOKEN_HEADER = "x-ra3copilot-token"
_PUBLIC_PATHS = {HEALTH_PATH, "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
_shutdown_token: str | None = None


def set_shutdown_token(token: str) -> None:
    global _shutdown_token
    _shutdown_token = token


def create_app() -> FastAPI:
    load_runtime_env()
    set_shutdown_token(get_or_create_token())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        qq_bot_service.configure_all_projects()
        try:
            yield
        finally:
            qq_bot_service.stop()

    app = FastAPI(title="Ra3Copilot Daemon", version="0.2.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_local_token(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in _PUBLIC_PATHS or path.startswith("/docs"):
            return await call_next(request)
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

        expected = _shutdown_token or get_or_create_token()
        provided = request.headers.get(_TOKEN_HEADER) or request.query_params.get("token") or ""
        if not secrets.compare_digest(provided, expected):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
        return await call_next(request)

    app.include_router(runs_api.router)
    app.include_router(context_api.router)
    app.include_router(projects_api.router)
    app.include_router(history_api.router)
    app.include_router(files_api.router)
    app.include_router(settings_api.router)
    app.include_router(terminal_api.router)
    app.include_router(usage_api.router)

    @app.get(HEALTH_PATH)
    def health():
        return JSONResponse(
            {
                "ok": True,
                "version": protocol.PROTOCOL_VERSION,
                "uptime": round(time.time() - _START_TIME, 2),
                "pid": os.getpid(),
            }
        )

    @app.get("/shutdown")
    async def shutdown(request: Request):
        """Graceful shutdown, localhost-only, guarded by a token.

        Used by a future tray menu / "quit core" action. The window process does
        not call this; the daemon is designed to stay resident.
        """
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
        provided = request.headers.get(_TOKEN_HEADER) or request.query_params.get("token") or ""
        if _shutdown_token and not secrets.compare_digest(provided, _shutdown_token):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
        clear_pidfile()
        # Schedule exit on the running loop.
        import asyncio

        loop = asyncio.get_event_loop()
        loop.call_later(0.1, lambda: os._exit(0))
        return JSONResponse({"ok": True})

    return app


def run_server(port: int) -> None:
    import uvicorn

    from desktop.tray import TrayController

    write_pidfile(port)
    app = create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # The tray lives in the daemon (singleton) process so there is exactly one
    # icon regardless of how many windows are open. "退出" stops the server,
    # which lets run_server() return and the process exit.
    tray = TrayController()

    def _quit_from_tray() -> None:
        server.should_exit = True

    tray.start(quit_app=_quit_from_tray)
    try:
        server.run()
    finally:
        tray.stop()
        clear_pidfile()
        os._exit(0)
