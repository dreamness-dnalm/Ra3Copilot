"""Runs API: start / poll / stop an agent run.

The body schema mirrors the old DesktopBridge method arguments. ``clientId``
scopes the single-active-run constraint per window.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from daemon.api.protocol import (
    fail,
    ok,
    RUN_ALREADY_ACTIVE,
    RUN_NOT_FOUND,
    UPSTREAM_ERROR,
)
from daemon.runtime import normalize_agent_mode
from daemon.supervisor import supervisor

router = APIRouter()


class StartRunBody(BaseModel):
    clientId: str
    threadId: str
    projectId: str | None = None
    agentMode: str | None = None
    text: str
    options: dict | None = None


class PollRunBody(BaseModel):
    runId: str
    maxEvents: int = 80


class StopRunBody(BaseModel):
    runId: str


@router.post("/runs/start")
def start_run(body: StartRunBody):
    prompt = (body.text or "").strip()
    if not prompt:
        return fail("请输入指令。", error_code=UPSTREAM_ERROR)

    options = body.options or {}
    agent_mode = normalize_agent_mode(body.agentMode or options.get("agentMode"))
    permission_policy = options.get("permissionPolicy", "once")

    try:
        state = supervisor.start_run(
            client_id=body.clientId,
            thread_id=body.threadId,
            project_id=body.projectId or "",
            agent_mode=agent_mode,
            prompt=prompt,
            permission_policy=permission_policy,
        )
    except RuntimeError as exc:
        if str(exc) == "RUN_ALREADY_ACTIVE":
            return fail("已有任务正在运行。", error_code=RUN_ALREADY_ACTIVE)
        return fail(str(exc))
    except Exception as exc:
        return fail(str(exc))

    from core.user_data.history import list_conversations
    from core.user_data.projects import open_project

    project = open_project(state.project_id)
    return ok(runId=state.run_id, history=list_conversations(project))


@router.post("/runs/poll")
def poll_run(body: PollRunBody):
    result = supervisor.poll_run(body.runId, body.maxEvents)
    if result is None:
        return fail("运行记录不存在。", error_code=RUN_NOT_FOUND)
    return ok(**result)


@router.post("/runs/stop")
def stop_run(body: StopRunBody):
    stopped = supervisor.stop_run(body.runId)
    if not stopped:
        return fail("没有正在运行的任务。", error_code=RUN_NOT_FOUND)
    return ok()
