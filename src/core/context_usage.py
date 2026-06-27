from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from core.agents.project_instructions import load_project_instruction_files
from core.agents.project_skills import load_project_skills
from core.user_data.config import get_active_model
from core.user_data.history import get_conversation
from core.user_data.provider import get_model_config


DEFAULT_CONTEXT_WINDOW_TOKENS = 258_000

_PROMPTS_ROOT = Path(__file__).resolve().parent / "prompts"
_RA3_AGENT_PROMPT_PATH = _PROMPTS_ROOT / "agents" / "ra3_csharp_writer.md"
_BUILTIN_SKILLS_ROOT = _PROMPTS_ROOT / "skills"

_DEEPAGENTS_TOOL_CONTEXT = """DeepAgents built-in tools available to the agent:
- write_todos: maintain the task plan/todo list.
- write_file: create or replace a project file.
- read_file: read a project file.
- edit_file: patch an existing project file.
- grep: search text in the project.
- glob: find files by pattern.
- ls: list project directories.
"""

_RA3_TOOL_CONTEXT = """RA3 Companion tools available in RA3 mode:
- get_map_list: read local RA3 map list.
- copy_ra3_map: copy a map before modifications.
- run_ra3_csharp_script: run C# scripts against RA3 maps.
- analyse_ra3_map: inspect map resources and player starts.
- get_lib_structure: inspect RA3 map editing library structure.
- get_type_info: inspect C# type information.
- get_method_signature: inspect C# method signatures.
"""


def _normalize_agent_mode(mode: str | None) -> str:
    if mode == "openclaw":
        return "assistant"
    return mode if mode in {"ra3", "universal", "assistant"} else "ra3"


def estimate_tokens(text: str | None) -> int:
    """Approximate model tokens without binding the app to one tokenizer."""
    if not text:
        return 0
    ascii_chars = 0
    non_ascii_chars = 0
    for char in str(text):
        if ord(char) < 128:
            ascii_chars += 1
        else:
            non_ascii_chars += 1
    return int(math.ceil((ascii_chars / 4.0) + (non_ascii_chars * 1.05)))


def _project_snapshot(project: Any) -> dict:
    if not project:
        return {}
    if hasattr(project, "model_dump"):
        return project.model_dump()
    if isinstance(project, dict):
        return dict(project)
    return {
        "id": getattr(project, "id", ""),
        "name": getattr(project, "name", ""),
        "path": getattr(project, "path", ""),
        "kind": getattr(project, "kind", ""),
    }


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _universal_system_prompt() -> str:
    try:
        from core.agents.universal import _SYSTEM_PROMPT

        return str(_SYSTEM_PROMPT or "")
    except Exception:
        return "You are Mia Copilot, a general-purpose assistant."


def _ra3_system_prompt() -> str:
    return _safe_read_text(_RA3_AGENT_PROMPT_PATH)


def _builtin_skill_paths() -> list[Path]:
    paths = sorted((_BUILTIN_SKILLS_ROOT / "csharp").glob("**/SKILL.md"))
    map_analyser = _BUILTIN_SKILLS_ROOT / "map-analyser" / "SKILL.md"
    if map_analyser.is_file():
        paths.append(map_analyser)
    return paths


def _builtin_skills_prompt() -> str:
    parts: list[str] = []
    for path in _builtin_skill_paths():
        text = _safe_read_text(path)
        if not text:
            continue
        parts.append(f"## Built-in skill: {path.parent.name}\n\n{text}")
    return "\n\n".join(parts)


def _project_context_prompt(project: dict) -> str:
    path = str(project.get("path") or "").strip()
    if not path:
        return ""
    name = str(project.get("name") or "").strip() or path
    kind = str(project.get("kind") or "").strip()
    lines = [
        "当前工作上下文：",
        f"- 工程名称：{name}",
    ]
    if kind:
        lines.append(f"- 工程类型：{kind}")
    lines.extend(
        [
            f"- 工程磁盘路径：{path}",
            "- 文件工具（write_file/read_file/edit_file/grep/glob/ls）操作的是该工程目录。",
            "- 请使用相对路径或以 / 开头的虚拟路径，不要在工具参数中使用 Windows 绝对路径。",
        ]
    )
    return "\n".join(lines)


def _tools_prompt(agent_mode: str) -> str:
    if agent_mode == "ra3":
        return f"{_DEEPAGENTS_TOOL_CONTEXT}\n\n{_RA3_TOOL_CONTEXT}"
    return _DEEPAGENTS_TOOL_CONTEXT


def _system_prompt(agent_mode: str) -> str:
    if agent_mode == "ra3":
        return _ra3_system_prompt()
    return _universal_system_prompt()


def _skills_prompt(agent_mode: str, project_path: str) -> str:
    parts: list[str] = []
    if agent_mode == "ra3":
        builtin = _builtin_skills_prompt()
        if builtin:
            parts.append(builtin)
    project_skills = load_project_skills(project_path)
    if project_skills:
        parts.append(project_skills)
    return "\n\n".join(parts)


def _instructions_prompt(project_path: str) -> str:
    if not project_path:
        return ""
    return load_project_instruction_files(project_path)


def _message_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value or "")


def _history_prompt(project: dict, thread_id: str | None) -> str:
    if not project or not thread_id:
        return ""
    try:
        conversation = get_conversation(project, thread_id)
    except Exception:
        return ""
    if not conversation:
        return ""

    parts: list[str] = []
    for message in conversation.get("messages") or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "message")
        content = _message_content_text(message.get("content"))
        if content:
            parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def _active_context_window_tokens() -> tuple[int, dict | None]:
    try:
        active = get_active_model()
    except Exception:
        return DEFAULT_CONTEXT_WINDOW_TOKENS, None
    if not active:
        return DEFAULT_CONTEXT_WINDOW_TOKENS, None

    provider_name, model_name = active
    model_info = {"provider_name": provider_name, "name": model_name}
    try:
        model_config = get_model_config(provider_name, model_name)
    except Exception:
        model_config = None
    if model_config is not None:
        model_info = model_config.model_dump()
        if model_config.context_length and model_config.context_length > 0:
            return int(model_config.context_length), model_info
    return DEFAULT_CONTEXT_WINDOW_TOKENS, model_info


def _section(section_id: str, label: str, text: str) -> dict:
    return {
        "id": section_id,
        "label": label,
        "chars": len(text or ""),
        "tokens": estimate_tokens(text),
    }


def estimate_context_usage(
    project: Any = None,
    thread_id: str | None = None,
    agent_mode: str | None = None,
    draft_text: str | None = None,
) -> dict:
    mode = _normalize_agent_mode(agent_mode)
    project_data = _project_snapshot(project)
    project_path = str(project_data.get("path") or "").strip()

    sections = [
        _section("system", "System", _system_prompt(mode)),
        _section("tools", "Tools", _tools_prompt(mode)),
        _section("skills", "Skills", _skills_prompt(mode, project_path)),
        _section("instructions", "Instructions", _instructions_prompt(project_path)),
        _section("project", "Project", _project_context_prompt(project_data)),
        _section("history", "History", _history_prompt(project_data, thread_id)),
        _section("draft", "Draft", str(draft_text or "")),
    ]

    used_tokens = sum(section["tokens"] for section in sections)
    used_chars = sum(section["chars"] for section in sections)
    max_tokens, model_info = _active_context_window_tokens()
    used_percent = (used_tokens / max_tokens) if max_tokens else 0

    for section in sections:
        section["percent"] = (section["tokens"] / used_tokens) if used_tokens else 0

    return {
        "estimate": True,
        "agentMode": mode,
        "usedTokens": used_tokens,
        "usedChars": used_chars,
        "maxTokens": max_tokens,
        "usedPercent": used_percent,
        "model": model_info,
        "sections": sections,
    }
