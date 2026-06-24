"""FastAPI application assembly for the daemon.

Mounts the runs router (Step 2) plus health/shutdown. Data-layer routers
(Step 3) are included there. CORS is permissive for localhost so a pywebview
``file://`` origin (and later Tauri/WPF) can call the API.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.runtime_env import load_runtime_env
from daemon.api import protocol
from daemon.api import runs as runs_api
from daemon.locking import HEALTH_PATH, clear_pidfile, write_pidfile

_START_TIME = time.time()
_shutdown_token: str | None = None


def set_shutdown_token(token: str) -> None:
    global _shutdown_token
    _shutdown_token = token


def create_app() -> FastAPI:
    load_runtime_env()
    app = FastAPI(title="Ra3Copilot Daemon", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(runs_api.router)

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
        if _shutdown_token and request.query_params.get("token") != _shutdown_token:
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
    server.run()
