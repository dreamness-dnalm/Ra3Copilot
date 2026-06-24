"""Context + agent-mode API.

``get_context`` returns the session snapshot the frontend uses to render the
status bar. Unlike the old DesktopBridge it is stateless: the caller passes
its current project/threadId/agentMode so the daemon holds no per-client state.

The RA3 Companion socket probe also lives here so it runs once per call rather
than per-window (the daemon is the single process that cares).
"""

from __future__ import annotations

import socket

from fastapi import APIRouter
from pydantic import BaseModel

from core.runtime_env import get_langsmith_status
from core.user_data.config import get_active_model
from core.user_data.projects import PROJECTS_DIR
from daemon.api.protocol import fail, ok
from daemon.runtime import agent_ready, normalize_agent_mode

router = APIRouter()

APP_TITLE = "Ra3Copilot"
RA3_COMPANION_HOST = "127.0.0.1"
RA3_COMPANION_PORT = 30033


def _model_label() -> str:
    try:
        active_model = get_active_model()
    except Exception as exc:
        return f"配置读取失败：{exc}"
    if active_model is None:
        return "未配置模型"
    provider_name, model_name = active_model
    return f"{provider_name}/{model_name}"


def _ra3_companion_status() -> dict:
    try:
        with socket.create_connection((RA3_COMPANION_HOST, RA3_COMPANION_PORT), timeout=0.25):
            return {
                "connected": True,
                "transport": "mcp",
                "host": RA3_COMPANION_HOST,
                "port": RA3_COMPANION_PORT,
                "label": "已连接",
            }
    except OSError as exc:
        return {
            "connected": False,
            "transport": "mcp",
            "host": RA3_COMPANION_HOST,
            "port": RA3_COMPANION_PORT,
            "label": "未连接",
            "error": str(exc),
        }


class ContextBody(BaseModel):
    project: dict | None = None
    threadId: str | None = None
    agentMode: str | None = None


@router.post("/context")
def get_context(body: ContextBody):
    project = body.project
    agent_mode = normalize_agent_mode(body.agentMode or "ra3")
    return ok(
        app=APP_TITLE,
        mode="desktop",
        projectRoot=(project or {}).get("path", "") if project else "",
        project=project,
        projectsDir=str(PROJECTS_DIR),
        threadId=body.threadId or "",
        model=_model_label(),
        agentMode=agent_mode,
        agentReady=agent_ready(agent_mode),
        langsmith=get_langsmith_status(),
        ra3Companion=_ra3_companion_status(),
    )


class AgentModeBody(BaseModel):
    agentMode: str = "ra3"
    project: dict | None = None
    threadId: str | None = None


@router.post("/agent/mode")
def set_agent_mode(body: AgentModeBody):
    mode = normalize_agent_mode(body.agentMode)
    # Mode is purely client-side state now; just echo it back with context.
    return ok(
        agentMode=mode,
        context={
            "agentMode": mode,
            "agentReady": agent_ready(mode),
            "model": _model_label(),
            "threadId": body.threadId or "",
            "project": body.project,
            "projectsDir": str(PROJECTS_DIR),
            "app": APP_TITLE,
            "mode": "desktop",
            "projectRoot": (body.project or {}).get("path", "") if body.project else "",
            "langsmith": get_langsmith_status(),
            "ra3Companion": _ra3_companion_status(),
        },
    )
