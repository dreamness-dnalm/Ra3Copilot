"""Chat history API.

Chat operations that mutated the window's threadId are now pure: the daemon
does not track which thread a client is viewing. ``new_chat`` just confirms no
active run blocks and returns a fresh thread id (generated client-side); the
others read/write the on-disk conversation store.

The active-run guard uses the per-clientId supervisor so two windows don't
block each other.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from core.user_data.history import (
    delete_conversation,
    get_conversation,
    list_conversations,
)
from core.user_data.projects import DEFAULT_PROJECT_ID, ProjectEntry, open_project
from daemon.api.protocol import fail, ok, RUN_ALREADY_ACTIVE
from daemon.supervisor import supervisor

router = APIRouter()


def _resolve(project_body: dict | None, project_id: str | None) -> ProjectEntry:
    if project_body:
        return ProjectEntry(**project_body)
    return open_project(project_id or DEFAULT_PROJECT_ID)


class ProjectRefBody(BaseModel):
    project: dict | None = None
    projectId: str | None = None


class HistoryBody(ProjectRefBody):
    pass


@router.post("/history/list")
def list_history(body: HistoryBody):
    project = _resolve(body.project, body.projectId)
    return ok(history=list_conversations(project))


class NewChatBody(ProjectRefBody):
    clientId: str | None = None
    threadId: str | None = None


@router.post("/history/new")
def new_chat(body: NewChatBody):
    if body.clientId and supervisor.has_active_run(body.clientId):
        return fail("当前仍有运行中的任务，先中止或等待完成。", error_code=RUN_ALREADY_ACTIVE)
    thread_id = body.threadId or uuid4().hex
    project = _resolve(body.project, body.projectId)
    return ok(threadId=thread_id, history=list_conversations(project))


class OpenChatBody(ProjectRefBody):
    clientId: str | None = None
    conversationId: str


@router.post("/history/open")
def open_chat(body: OpenChatBody):
    if body.clientId and supervisor.has_active_run(body.clientId):
        return fail("当前仍有运行中的任务，请先中止或等待完成。", error_code=RUN_ALREADY_ACTIVE)
    project = _resolve(body.project, body.projectId)
    conversation = get_conversation(project, body.conversationId)
    if conversation is None:
        return fail("对话记录不存在。")
    return ok(conversation=conversation, history=list_conversations(project))


class DeleteChatBody(ProjectRefBody):
    clientId: str | None = None
    conversationId: str


@router.post("/history/delete")
def delete_chat(body: DeleteChatBody):
    if body.clientId and supervisor.has_active_run(body.clientId):
        return fail("当前仍有运行中的任务，请先中止或等待完成。", error_code=RUN_ALREADY_ACTIVE)
    project = _resolve(body.project, body.projectId)
    deleted = delete_conversation(project, body.conversationId)
    return ok(deleted=deleted, history=list_conversations(project))
