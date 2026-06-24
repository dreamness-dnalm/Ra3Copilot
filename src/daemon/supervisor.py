"""RunSupervisor: owns the agent run lifecycle, ported from DesktopBridge.

Concurrency model is **one active run per client** (``clientId``). A window is
one client; multiple windows can each run their own task in parallel. Within a
single client, starting a new run while one is active is rejected — matching
the old per-window single-run semantics.

Each run executes in a daemon thread that spins up its own asyncio loop (same
as before). Streamed chunks are converted to the frozen event schema and
pushed onto an in-process queue; the window polls them via the runs API.
"""

from __future__ import annotations

import asyncio
import json
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from time import perf_counter
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

from core.user_data.config import get_active_model
from core.user_data.history import append_message
from core.user_data.provider import ModelConfig, get_model_config
from core.user_data.projects import DEFAULT_PROJECT_ID, open_project
from core.user_data.usage import (
    TokenUsage,
    calculate_cost,
    merge_token_usage,
    record_usage_run,
    usage_from_message,
)

from daemon.api.protocol import (
    EVENT_ASSISTANT_DELTA,
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_RUN_STARTED,
    EVENT_STATUS,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    TERMINAL_STATUSES,
)
from daemon.runtime import (
    LOCAL_SKILL_SUMMARY,
    decode_tool_args,
    exception_message,
    exception_trace,
    flatten_exception_messages,
    local_reply_for_prompt,
    message_text,
    normalize_agent_mode,
    prompt_for_policy,
    tool_result_text,
)


MAX_TOOL_RESULT_CHARS = 12000


@dataclass
class RunState:
    run_id: str
    client_id: str
    thread_id: str
    agent_mode: str
    project_id: str
    permission_policy: str
    events: Queue[dict] = field(default_factory=Queue)
    status: str = "queued"
    error: str | None = None
    assistant_text: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    provider_name: str = ""
    model_name: str = ""
    model_config: ModelConfig | None = None
    usage_recorded: bool = False
    started_at: float = field(default_factory=perf_counter)
    cancel_requested: threading.Event = field(default_factory=threading.Event)

    def emit(self, event: dict) -> None:
        self.events.put(event)


class RunSupervisor:
    """Tracks active runs keyed by clientId, enforcing per-client single-run."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._active_by_client: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- query helpers ----------------------------------------------------

    def get_run(self, run_id: str) -> RunState | None:
        with self._lock:
            return self._runs.get(run_id)

    def active_run_id(self, client_id: str) -> str | None:
        with self._lock:
            return self._active_by_client.get(client_id)

    def has_active_run(self, client_id: str) -> bool:
        return self.active_run_id(client_id) is not None

    # -- start ------------------------------------------------------------

    def start_run(
        self,
        *,
        client_id: str,
        thread_id: str,
        project_id: str,
        agent_mode: str,
        prompt: str,
        permission_policy: str,
    ) -> RunState:
        """Create a run state and launch its worker thread.

        Raises ``RuntimeError`` if the client already has an active run. The
        caller maps that to the DAEMON_BUSY/RUN_ALREADY_ACTIVE error code.
        """
        with self._lock:
            if client_id in self._active_by_client:
                raise RuntimeError("RUN_ALREADY_ACTIVE")
            run_id = uuid4().hex
            state = RunState(
                run_id=run_id,
                client_id=client_id,
                thread_id=thread_id,
                agent_mode=normalize_agent_mode(agent_mode),
                project_id=project_id or DEFAULT_PROJECT_ID,
                permission_policy=permission_policy or "once",
            )
            self._capture_model(state)
            self._runs[run_id] = state
            self._active_by_client[client_id] = run_id

        # Persist the user message before streaming so it survives crashes.
        project = open_project(state.project_id)
        append_message(project, state.thread_id, "user", prompt)

        worker = threading.Thread(
            target=self._run_worker,
            args=(state, prompt),
            name=f"{state.agent_mode}-agent-{run_id[:8]}",
            daemon=True,
        )
        worker.start()
        return state

    def _capture_model(self, state: RunState) -> None:
        try:
            active_model = get_active_model()
            if active_model:
                state.provider_name, state.model_name = active_model
                state.model_config = get_model_config(state.provider_name, state.model_name)
        except Exception:
            pass

    # -- poll / stop ------------------------------------------------------

    def poll_run(self, run_id: str, max_events: int = 80) -> dict | None:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            return None

        events = []
        for _ in range(max_events):
            try:
                events.append(state.events.get_nowait())
            except Empty:
                break

        finished = state.status in TERMINAL_STATUSES
        if finished and not events:
            with self._lock:
                self._runs.pop(run_id, None)
                if self._active_by_client.get(state.client_id) == run_id:
                    # Already cleared by worker; keep defensive pop anyway.
                    self._active_by_client.pop(state.client_id, None)

        return {
            "status": state.status,
            "events": events,
            "error": state.error,
            "elapsed": round(perf_counter() - state.started_at, 2),
        }

    def stop_run(self, run_id: str) -> bool:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            return False
        state.cancel_requested.set()
        state.emit({"type": EVENT_STATUS, "text": "已请求中止，等待当前响应片段结束。"})
        return True

    # -- worker -----------------------------------------------------------

    def _run_worker(self, state: RunState, prompt: str) -> None:
        try:
            asyncio.run(self._run_agent(state, prompt))
        finally:
            with self._lock:
                if self._active_by_client.get(state.client_id) == state.run_id:
                    self._active_by_client.pop(state.client_id, None)

    async def _run_agent(self, state: RunState, prompt: str) -> None:
        from daemon.runtime import ensure_agent  # local import to avoid cycle

        state.status = "running"
        state.emit(
            {
                "type": EVENT_RUN_STARTED,
                "runId": state.run_id,
                "threadId": state.thread_id,
                "permissionPolicy": state.permission_policy,
                "agentMode": state.agent_mode,
            }
        )

        project = open_project(state.project_id)
        tool_calls: dict[str, dict] = {}
        try:
            # Local shortcut: RA3 mode asking for the skill list.
            local_reply = (
                local_reply_for_prompt(prompt)
                if state.agent_mode == "ra3"
                else None
            )
            if local_reply:
                state.usage = TokenUsage(usage_known=True)
                state.assistant_text += local_reply
                state.emit(
                    {
                        "type": EVENT_ASSISTANT_DELTA,
                        "messageId": "assistant",
                        "text": local_reply,
                    }
                )
                state.status = "done"
                self._save_assistant_message(state, project, "done")
                state.emit(self._done_event(state, project, "done"))
                return

            agent = await ensure_agent(state)
            config = {
                "configurable": {"thread_id": state.thread_id},
                "run_name": "Ra3Copilot daemon conversation",
                "tags": ["ra3-copilot", "daemon"],
                "metadata": {
                    "app": "Ra3Copilot",
                    "thread_id": state.thread_id,
                    "permission_policy": state.permission_policy,
                    "agent_mode": state.agent_mode,
                    "project_id": state.project_id,
                },
            }

            effective_prompt = prompt_for_policy(prompt, state.permission_policy)
            async for chunk, _meta in agent.astream(
                {"messages": [HumanMessage(effective_prompt)]},
                config,
                stream_mode="messages",
            ):
                if state.cancel_requested.is_set():
                    state.status = "cancelled"
                    self._save_assistant_message(state, project, "cancelled")
                    state.emit(self._done_event(state, project, "cancelled"))
                    return

                if isinstance(chunk, AIMessageChunk):
                    state.usage = merge_token_usage(state.usage, usage_from_message(chunk))
                    for tool_call in chunk.tool_call_chunks or []:
                        tool_id = tool_call.get("id") or f"tool-{tool_call.get('index', 0)}"
                        known_call = tool_calls.setdefault(
                            tool_id,
                            {
                                "id": tool_id,
                                "name": tool_call.get("name") or "工具调用",
                                "args": "",
                                "startedAt": perf_counter(),
                                "status": "pending",
                            },
                        )
                        if tool_call.get("name"):
                            known_call["name"] = tool_call["name"]
                            known_call["status"] = "running"
                            state.emit(
                                {
                                    "type": EVENT_TOOL_CALL,
                                    "tool": {
                                        "id": tool_id,
                                        "name": known_call["name"],
                                        "status": "running",
                                        "args": decode_tool_args(known_call["args"]),
                                    },
                                }
                            )
                        if tool_call.get("args"):
                            known_call["args"] += tool_call["args"]

                    piece = message_text(chunk)
                    if piece:
                        state.assistant_text += piece
                        state.emit(
                            {
                                "type": EVENT_ASSISTANT_DELTA,
                                "messageId": chunk.id or "assistant",
                                "text": piece,
                            }
                        )

                elif isinstance(chunk, ToolMessage):
                    tool_id = (
                        getattr(chunk, "tool_call_id", None)
                        or getattr(chunk, "name", None)
                        or f"tool-{len(tool_calls)}"
                    )
                    known_call = tool_calls.setdefault(
                        tool_id,
                        {
                            "id": tool_id,
                            "name": getattr(chunk, "name", None) or tool_id,
                            "args": "",
                            "startedAt": perf_counter(),
                            "status": "running",
                        },
                    )
                    known_call["status"] = "completed"
                    elapsed = perf_counter() - known_call["startedAt"]
                    state.emit(
                        {
                            "type": EVENT_TOOL_RESULT,
                            "tool": {
                                "id": tool_id,
                                "name": getattr(chunk, "name", None) or known_call["name"],
                                "status": "completed",
                                "args": decode_tool_args(known_call["args"]),
                                "result": tool_result_text(chunk.content, MAX_TOOL_RESULT_CHARS),
                                "elapsed": round(elapsed, 2),
                            },
                        }
                    )

            state.status = "done"
            self._save_assistant_message(state, project, "done")
            state.emit(self._done_event(state, project, "done"))
        except Exception as exc:
            trace = exception_trace(exc)
            message = exception_message(exc)
            state.status = "error"
            state.error = message
            error_text = f"运行出错：{message}"
            state.assistant_text = (
                f"{state.assistant_text.rstrip()}\n\n{error_text}"
                if state.assistant_text.strip()
                else error_text
            )
            self._save_assistant_message(state, project, "error")

            for tool_id, known_call in tool_calls.items():
                if known_call.get("status") == "completed":
                    continue
                known_call["status"] = "error"
                elapsed = perf_counter() - known_call["startedAt"]
                state.emit(
                    {
                        "type": EVENT_TOOL_RESULT,
                        "tool": {
                            "id": tool_id,
                            "name": known_call.get("name") or tool_id,
                            "status": "error",
                            "args": decode_tool_args(known_call.get("args", "")),
                            "result": f"{message}\n\n{trace}",
                            "elapsed": round(elapsed, 2),
                        },
                    }
                )

            from core.user_data.history import list_conversations

            state.emit(
                {
                    "type": EVENT_ERROR,
                    "message": message,
                    "trace": trace,
                    "history": list_conversations(project),
                }
            )
            state.emit(self._done_event(state, project, "error"))

    # -- persistence helpers ---------------------------------------------

    def _save_assistant_message(self, state: RunState, project, status: str) -> None:
        content = state.assistant_text.strip()
        if not content and status == "cancelled":
            content = "本轮运行已中止。"
        if not content:
            return
        try:
            append_message(project, state.thread_id, "assistant", content, status=status)
        except Exception as exc:
            state.emit({"type": EVENT_STATUS, "text": f"保存对话历史失败：{exc}"})

    def _record_usage(self, state: RunState, status: str) -> dict | None:
        if state.usage_recorded:
            return None
        state.usage_recorded = True
        model_config = state.model_config
        currency = (getattr(model_config, "currency", None) or "CNY").upper()
        cost = None
        if model_config is not None:
            cost, currency = calculate_cost(state.usage, model_config)
        try:
            project = open_project(state.project_id)
            return record_usage_run(
                run_id=state.run_id,
                conversation_id=state.thread_id,
                project=project,
                provider_name=state.provider_name,
                model_name=state.model_name,
                status=status,
                usage=state.usage,
                cost=cost,
                currency=currency,
            )
        except Exception as exc:
            state.emit({"type": EVENT_STATUS, "text": f"保存用量统计失败：{exc}"})
            return None

    def _done_event(self, state: RunState, project, status: str) -> dict:
        from core.user_data.history import list_conversations

        usage = self._record_usage(state, status)
        return {
            "type": EVENT_DONE,
            "status": status,
            "history": list_conversations(project),
            "usage": usage,
        }


# Module-level singleton: one supervisor per daemon process.
supervisor = RunSupervisor()
