"""Usage statistics API."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.user_data.usage import get_conversation_usage, get_usage_summary
from daemon.api.protocol import ok

router = APIRouter()


class SummaryBody(BaseModel):
    days: int = 365


@router.post("/usage/summary")
def usage_summary(body: SummaryBody):
    return ok(usage=get_usage_summary(body.days))


class ConversationUsageBody(BaseModel):
    conversationId: str | None = None


@router.post("/usage/conversation")
def conversation_usage(body: ConversationUsageBody):
    target_id = body.conversationId or ""
    if not target_id:
        return ok(usage=get_conversation_usage(""))
    return ok(usage=get_conversation_usage(target_id))
