"""Daemon IPC protocol: unified response envelope, error codes, and the
streaming event schema.

Every endpoint returns ``{"ok": bool, ...}``. On failure it carries ``error``
(human-readable message) and optionally ``errorCode`` (machine-readable).
The frontend only inspects ``ok`` and ``error``/``errorCode``, mirroring the
existing ``{ok, error?, ...payload}`` contract from DesktopBridge.
"""

from __future__ import annotations

from typing import Any

# Bumped only on incompatible changes to the event/response schema.
PROTOCOL_VERSION = 1

# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
DAEMON_BUSY = "DAEMON_BUSY"
RUN_NOT_FOUND = "RUN_NOT_FOUND"
RUN_ALREADY_ACTIVE = "RUN_ALREADY_ACTIVE"
PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
UPSTREAM_ERROR = "UPSTREAM_ERROR"


def ok(**payload: Any) -> dict:
    """Build a success response."""
    return {"ok": True, **payload}


def fail(message: str, *, error_code: str = UPSTREAM_ERROR, **payload: Any) -> dict:
    """Build a failure response."""
    return {"ok": False, "error": message, "errorCode": error_code, **payload}


# ---------------------------------------------------------------------------
# Streaming event helpers
#
# The event shapes below are frozen copies of what DesktopBridge._run_agent
# emits today, so the frontend's handleAgentEvent() dispatch keeps working
# unchanged. The "type" values are the contract.
# ---------------------------------------------------------------------------

EVENT_RUN_STARTED = "run_started"
EVENT_STATUS = "status"
EVENT_ASSISTANT_DELTA = "assistant_delta"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_ERROR = "error"
EVENT_DONE = "done"

TERMINAL_STATUSES = {"done", "error", "cancelled"}
