"""Agent runtime helpers: pure functions ported from DesktopBridge, plus the
per-mode agent cache and ``ensure_agent``.

The agent cache is keyed by mode, project, and project-local skills, so the
(expensive) agent construction and MCP tool handshake are reused until needed.
The ``configurable_model`` middleware re-reads the active model on every call,
so changing settings does NOT require rebuilding agents. A settings change just
needs to invalidate this cache (see ``reset_agents``).
"""

from __future__ import annotations

import json
import threading
import traceback

from core.agents.ra3_csharp_writer import create_ra3_csharp_writer_agent
from core.agents.project_skills import project_skills_signature
from core.agents.universal import create_universal_agent
from core.runtime_env import load_runtime_env

LOCAL_SKILL_SUMMARY = """当前内置的 agent skill：

- `ra3_map_csharp`：RA3 地图 C# 编写规范。覆盖新建地图、保存地图、尺寸/边界约定、常用 using、地图命名等。
- `csharp_runner`：C# 脚本运行规范。用于生成最小可运行脚本、读取/修改地图、处理编译错误和运行错误。
- `map-analyser`：RA3 地图分析。通过 `analyse_ra3_map` 工具提取出生点、油井、观测站、矿脉及推荐矿场位置。

项目级 skill：

- 当前项目的 `.agent/skills/**/SKILL.md` 会自动加载到 Agent 系统提示中；新增或修改后，下一轮对话会重建该项目的 Agent 缓存。

可用的 RA3 Companion 工具：

- `get_map_list`：读取本机 RA3 地图列表。
- `copy_ra3_map`：复制地图用于修改。
- `run_ra3_csharp_script`：运行 C# 脚本处理地图。
- `analyse_ra3_map`：按 map-analyser skill 分析已有地图资源分布。
- `get_lib_structure`：查看 RA3 地图编辑库结构。
- `get_type_info`：查看类型信息。
- `get_method_signature`：查看方法签名。
"""


# ---------------------------------------------------------------------------
# Pure helpers (ported verbatim from desktop/app.py)
# ---------------------------------------------------------------------------

def normalize_agent_mode(mode: str | None) -> str:
    if mode == "openclaw":
        return "assistant"
    return mode if mode in {"ra3", "universal", "assistant"} else "ra3"


def message_text(message) -> str:
    """Return text from LangChain message chunks across package versions."""
    text = message.text
    text = text() if callable(text) else text
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        parts = []
        for block in text:
            if isinstance(block, dict):
                parts.append(str(block.get("text", block)))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(text or "")


def tool_result_text(content, max_chars: int) -> str:
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", block)))
            else:
                parts.append(str(block))
        text = "\n".join(parts)
    else:
        text = str(content)

    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        pass

    if len(text) > max_chars:
        return text[:max_chars] + "\n...(结果过长，已截断预览)"
    return text


def decode_tool_args(args: str):
    if not args:
        return {}
    try:
        return json.loads(args)
    except json.JSONDecodeError:
        return args


def flatten_exception_messages(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        messages: list[str] = []
        for index, inner in enumerate(exc.exceptions, 1):
            for message in _flatten(inner):
                messages.append(f"{index}. {message}")
        return messages
    return [f"{type(exc).__name__}: {exc}"]


_flatten = flatten_exception_messages  # internal recursion alias


def exception_message(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        details = "\n".join(flatten_exception_messages(exc))
        return f"{type(exc).__name__}: {exc}\n{details}"
    return str(exc)


def exception_trace(exc: BaseException) -> str:
    return "".join(
        traceback.TracebackException.from_exception(exc, capture_locals=False).format(chain=True)
    )


def local_reply_for_prompt(prompt: str) -> str | None:
    normalized = prompt.lower().replace(" ", "")
    asks_skill = "skill" in normalized or "技能" in normalized or "能力" in normalized
    asks_list = any(
        token in normalized
        for token in ("哪些", "有哪", "有什么", "有啥", "列表", "列出", "list", "show")
    )
    if asks_skill and asks_list:
        return LOCAL_SKILL_SUMMARY
    return None


def prompt_for_policy(prompt: str, policy: str) -> str:
    if policy == "remember":
        return (
            "本轮请优先使用只读方式分析。涉及写入文件、复制地图、运行会修改状态的脚本、"
            "或其他不可逆操作前，先向用户解释计划并等待确认。\n\n用户请求："
            f"{prompt}"
        )
    if policy == "explain":
        return (
            "本轮先不要调用工具。请先说明你的检查/修改计划、需要用户核对的信息，"
            "以及下一步会调用哪些工具。\n\n用户请求："
            f"{prompt}"
        )
    return prompt


# ---------------------------------------------------------------------------
# Agent cache
# ---------------------------------------------------------------------------

_agents: dict[tuple[str, str, str], object] = {}
_agent_lock = threading.Lock()


async def ensure_agent(state) -> object:
    """Return the cached agent for the active mode, project, and project skills.

    The agent's filesystem backend is rooted at the project directory, so the
    cache is keyed by mode, project, and project-local skills. Switching
    projects or changing ``.agent/skills`` builds a fresh agent with a
    correctly-rooted backend. ``state`` must expose ``agent_mode``,
    ``project_id`` and an ``emit(event)`` method for streaming init status.
    """
    from core.user_data.projects import DEFAULT_PROJECT_ID, open_project

    agent_mode = normalize_agent_mode(state.agent_mode)
    project_id = state.project_id or DEFAULT_PROJECT_ID

    project = open_project(project_id)
    project_path = str(getattr(project, "path", "") or "").strip()
    if not project_path:
        raise RuntimeError(f"工程路径为空：{project_id}")

    skills_signature = project_skills_signature(project_path)
    cache_key = (agent_mode, project_id, skills_signature)

    cached = _agents.get(cache_key)
    if cached is not None:
        return cached

    label_by_mode = {
        "ra3": "RA3 Agent",
        "universal": "万能 Agent",
        "assistant": "得力助手 Agent",
    }
    label = label_by_mode.get(agent_mode, "Agent")
    state.emit({"type": "status", "text": f"正在初始化 {label}..."})
    with _agent_lock:
        needs_init = cache_key not in _agents
    if needs_init:
        if agent_mode in {"universal", "assistant"}:
            agent = await create_universal_agent(project_path)
        else:
            agent = await create_ra3_csharp_writer_agent(project_path)
        with _agent_lock:
            for key in list(_agents):
                if key[:2] == cache_key[:2] and key != cache_key:
                    _agents.pop(key, None)
            _agents[cache_key] = agent
    state.emit({"type": "status", "text": "Agent 已就绪。"})
    return _agents[cache_key]


def reset_agents() -> None:
    """Drop cached agents so the next run rebuilds them.

    Called after provider/model/observability changes. The checkpointer is
    unaffected (it persists across rebuilds).
    """
    with _agent_lock:
        _agents.clear()


def agent_ready(agent_mode: str) -> bool:
    mode = normalize_agent_mode(agent_mode)
    return any(key[0] == mode for key in _agents)
