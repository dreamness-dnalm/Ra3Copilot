"""Middleware that injects the active project context into the system prompt.

The supervisor sets ``project_id`` in the run config's ``metadata`` on every
agent invocation (see ``supervisor._run_agent``). This middleware reads that id
on **every** model call, resolves the project path/name, and appends a short
context block to the system message so the model always knows which working
directory it is operating in — even many turns into a multi-turn conversation.

Why a middleware (vs. baking the path into the system prompt at agent build
time): the agent is cached across runs and across different projects, so the
prompt cannot be fixed at construction. Because the checkpointer replays only
the user/assistant messages, a path placed in the first user message would be
invisible in later turns; injecting it into the system message each turn keeps
it permanently in context.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import SystemMessage

from core.agents.project_instructions import load_project_instruction_files
from core.user_data.projects import DEFAULT_PROJECT_ID, open_project


def _resolve_project_context(project_id: str | None) -> str | None:
    """Return a context string for the project, or None if it can't be resolved."""
    if not project_id:
        return None
    try:
        project = open_project(project_id or DEFAULT_PROJECT_ID)
    except Exception:
        return None
    path = (getattr(project, "path", "") or "").strip()
    name = (getattr(project, "name", "") or "").strip() or path
    kind = getattr(project, "kind", "") or ""
    if not path:
        return None
    lines = ["当前工作上下文：", f"- 工程名称：{name}"]
    if kind:
        lines.append(f"- 工程类型：{kind}")
    lines.append(f"- 工程磁盘路径：{path}")
    lines.append(
        "- 文件工具（write_file/read_file/edit_file/grep/glob/ls）操作的就是该工程目录。"
        "请使用相对路径或以 / 开头的虚拟路径（如 /a.md 或 docs/readme.md），"
        "路径会自动解析到工程根目录下；不要使用 Windows 绝对路径（如 C:\\...）。"
    )
    instruction_block = load_project_instruction_files(path)
    if instruction_block:
        lines.extend(["", instruction_block])
    return "\n".join(lines)


@wrap_model_call
async def project_context(
    request,
    handler: Callable[..., Awaitable],
):
    from langgraph.config import get_config

    try:
        config = get_config() or {}
    except RuntimeError:
        # No runnable config in context (e.g. ad-hoc calls); skip injection.
        return await handler(request)

    metadata = config.get("metadata") or {}
    project_id = metadata.get("project_id")

    context_block = _resolve_project_context(project_id)
    if not context_block:
        return await handler(request)

    existing = request.system_message
    if existing is None:
        new_system = SystemMessage(content=context_block)
    else:
        new_system = SystemMessage(content=f"{existing.content}\n\n{context_block}")
    return await handler(request.override(system_message=new_system))
