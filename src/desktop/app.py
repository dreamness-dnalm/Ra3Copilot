from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from time import perf_counter
from uuid import uuid4

import webview
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
from webview.window import FixPoint

from core.agents.ra3_csharp_writer import create_ra3_csharp_writer_agent
from core.runtime_env import get_langsmith_status, load_runtime_env
from core.user_data.config import get_active_model
from core.user_data.history import (
    append_message,
    delete_conversation,
    get_conversation,
    list_conversations,
)
from core.user_data.project_files import (
    create_project_item,
    delete_project_item,
    list_project_files,
    read_project_file,
    rename_project_item,
    save_project_file,
)
from core.user_data.provider import (
    ModelConfig,
    ModelInfo,
    ProviderConfig,
    add_provider_config,
    cache_provider_models,
    fetch_available_models,
    remove_model_config,
    remove_provider_config,
    get_model_config,
    set_active_configured_model,
    set_models_for_provider,
    settings_snapshot,
    test_provider_connection,
    update_provider_config,
    upsert_model_config,
)
from core.user_data.projects import (
    DEFAULT_PROJECT_ID,
    PROJECTS_DIR,
    ProjectEntry,
    create_map_project_at,
    list_projects,
    open_map_project_from_directory,
    open_map_project_from_file,
    open_project,
    remove_recent_project,
)
from core.user_data.usage import (
    TokenUsage,
    calculate_cost,
    get_conversation_usage,
    get_usage_summary,
    merge_token_usage,
    record_usage_run,
    usage_from_message,
)


APP_TITLE = "Ra3Copilot"
MAX_TOOL_RESULT_CHARS = 12000
MIN_WINDOW_WIDTH = 980
MIN_WINDOW_HEIGHT = 640
RA3_COMPANION_HOST = "127.0.0.1"
RA3_COMPANION_PORT = 30033

LOCAL_SKILL_SUMMARY = """当前内置的 agent skill：

- `ra3_map_csharp`：RA3 地图 C# 编写规范。覆盖新建地图、保存地图、尺寸/边界约定、常用 using、地图命名等。
- `csharp_runner`：C# 脚本运行规范。用于生成最小可运行脚本、读取/修改地图、处理编译错误和运行错误。
- `map-analyser`：RA3 地图分析。通过 `analyse_ra3_map` 工具提取出生点、油井、观测站、矿脉及推荐矿场位置。

可用的 RA3 Companion 工具：

- `get_map_list`：读取本机 RA3 地图列表。
- `copy_ra3_map`：复制地图用于修改。
- `run_ra3_csharp_script`：运行 C# 脚本处理地图。
- `analyse_ra3_map`：按 map-analyser skill 分析已有地图资源分布。
- `get_lib_structure`：查看 RA3 地图编辑库结构。
- `get_type_info`：查看类型信息。
- `get_method_signature`：查看方法签名。
"""


def _web_index_path() -> Path:
    """Return the frontend file path both in source and PyInstaller builds."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "desktop" / "web" / "index.html"
    return Path(__file__).resolve().parent / "web" / "index.html"


@dataclass
class RunState:
    run_id: str
    thread_id: str = ""
    project: ProjectEntry | None = None
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


def _message_text(message) -> str:
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


def _tool_result_text(content) -> str:
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

    if len(text) > MAX_TOOL_RESULT_CHARS:
        return text[:MAX_TOOL_RESULT_CHARS] + "\n...(结果过长，已截断预览)"
    return text


def _decode_tool_args(args: str):
    if not args:
        return {}
    try:
        return json.loads(args)
    except json.JSONDecodeError:
        return args


def _flatten_exception_messages(exc: BaseException) -> list[str]:
    if isinstance(exc, BaseExceptionGroup):
        messages: list[str] = []
        for index, inner in enumerate(exc.exceptions, 1):
            for message in _flatten_exception_messages(inner):
                messages.append(f"{index}. {message}")
        return messages
    return [f"{type(exc).__name__}: {exc}"]


def _exception_message(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        details = "\n".join(_flatten_exception_messages(exc))
        return f"{type(exc).__name__}: {exc}\n{details}"
    return str(exc)


def _exception_trace(exc: BaseException) -> str:
    return "".join(
        traceback.TracebackException.from_exception(exc, capture_locals=False).format(chain=True)
    )


def _local_reply_for_prompt(prompt: str) -> str | None:
    normalized = prompt.lower().replace(" ", "")
    asks_skill = "skill" in normalized or "技能" in normalized or "能力" in normalized
    asks_list = any(
        token in normalized
        for token in ("哪些", "有哪", "有什么", "有啥", "列表", "列出", "list", "show")
    )
    if asks_skill and asks_list:
        return LOCAL_SKILL_SUMMARY
    return None


def _ra3_companion_status() -> dict:
    try:
        with socket.create_connection(
            (RA3_COMPANION_HOST, RA3_COMPANION_PORT),
            timeout=0.25,
        ):
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


def _prompt_for_policy(prompt: str, policy: str) -> str:
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


class DesktopBridge:
    """JS bridge that adapts the LangGraph agent to the desktop frontend."""

    def __init__(self) -> None:
        self.agent = None
        self.thread_id = uuid4().hex
        self.current_project: ProjectEntry | None = None
        self._agent_lock = threading.Lock()
        self._runs: dict[str, RunState] = {}
        self._runs_lock = threading.Lock()
        self._active_run_id: str | None = None
        self._window = None
        self._is_maximized = False

    def bind_window(self, window) -> None:
        self._window = window

    def _window_action(self, action: str) -> dict:
        if self._window is None:
            return {"ok": False, "error": "窗口尚未就绪。"}
        try:
            if action == "minimize":
                self._window.minimize()
            elif action == "toggle_maximize":
                if self._is_maximized:
                    self._window.restore()
                else:
                    self._window.maximize()
                self._is_maximized = not self._is_maximized
            elif action == "close":
                self._window.destroy()
            else:
                return {"ok": False, "error": f"未知窗口动作：{action}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def minimize_window(self) -> dict:
        return self._window_action("minimize")

    def toggle_maximize_window(self) -> dict:
        return self._window_action("toggle_maximize")

    def close_window(self) -> dict:
        return self._window_action("close")

    def resize_window_by(self, edge: str, delta_x: int | float = 0, delta_y: int | float = 0) -> dict:
        if self._window is None:
            return {"ok": False, "error": "窗口尚未就绪。"}

        edge_text = str(edge or "").lower()
        try:
            dx = int(round(float(delta_x or 0)))
            dy = int(round(float(delta_y or 0)))
            width = int(getattr(self._window, "width", MIN_WINDOW_WIDTH) or MIN_WINDOW_WIDTH)
            height = int(getattr(self._window, "height", MIN_WINDOW_HEIGHT) or MIN_WINDOW_HEIGHT)

            new_width = width
            new_height = height
            if "e" in edge_text:
                new_width += dx
            if "w" in edge_text:
                new_width -= dx
            if "s" in edge_text:
                new_height += dy
            if "n" in edge_text:
                new_height -= dy

            new_width = max(MIN_WINDOW_WIDTH, new_width)
            new_height = max(MIN_WINDOW_HEIGHT, new_height)

            horizontal_fix = FixPoint.EAST if "w" in edge_text else FixPoint.WEST
            vertical_fix = FixPoint.SOUTH if "n" in edge_text else FixPoint.NORTH
            self._window.resize(new_width, new_height, horizontal_fix | vertical_fix)
            self._is_maximized = False
            return {"ok": True, "width": new_width, "height": new_height}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_new_window(self) -> dict:
        try:
            if getattr(sys, "frozen", False):
                command = [sys.executable]
                cwd = Path(sys.executable).resolve().parent
            else:
                src_root = Path(__file__).resolve().parents[1]
                command = [sys.executable, "-m", "desktop.app"]
                if "--debug" in sys.argv:
                    command.append("--debug")
                cwd = src_root

            subprocess.Popen(
                command,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def open_project_folder(self) -> dict:
        try:
            project = self._ensure_active_project()
            project_path = Path(project.path).expanduser().resolve(strict=False)
            project_path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer.exe", str(project_path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(project_path)])
            else:
                subprocess.Popen(["xdg-open", str(project_path)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_project_terminal(self) -> dict:
        try:
            project = self._ensure_active_project()
            project_path = Path(project.path).expanduser().resolve(strict=False)
            project_path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                quoted_path = "'" + str(project_path).replace("'", "''") + "'"
                subprocess.Popen(
                    [
                        "cmd.exe",
                        "/c",
                        "start",
                        "",
                        "powershell.exe",
                        "-NoExit",
                        "-NoLogo",
                        "-Command",
                        f"Set-Location -LiteralPath {quoted_path}",
                    ]
                )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(project_path)])
            else:
                subprocess.Popen(["x-terminal-emulator", "--working-directory", str(project_path)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _model_label(self) -> str:
        try:
            active_model = get_active_model()
        except Exception as exc:
            return f"配置读取失败：{exc}"
        if active_model is None:
            return "未配置模型"
        provider_name, model_name = active_model
        return f"{provider_name}/{model_name}"

    def _reset_agent(self) -> None:
        with self._agent_lock:
            self.agent = None

    def _ensure_active_project(self) -> ProjectEntry:
        if self.current_project is None:
            self.current_project = open_project(DEFAULT_PROJECT_ID)
        return self.current_project

    def _history_snapshot(self, project: ProjectEntry | None = None) -> list[dict]:
        active_project = project or self._ensure_active_project()
        return list_conversations(active_project)

    def get_context(self) -> dict:
        project = self.current_project
        return {
            "app": APP_TITLE,
            "mode": "desktop",
            "projectRoot": project.path if project else "",
            "project": project.model_dump() if project else None,
            "projectsDir": str(PROJECTS_DIR),
            "threadId": self.thread_id,
            "model": self._model_label(),
            "agentReady": self.agent is not None,
            "langsmith": get_langsmith_status(),
            "ra3Companion": _ra3_companion_status(),
        }

    def get_settings(self) -> dict:
        try:
            return {"ok": True, "settings": settings_snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_usage_summary(self, days: int = 365) -> dict:
        try:
            return {"ok": True, "usage": get_usage_summary(days)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_conversation_usage(self, conversation_id: str | None = None) -> dict:
        try:
            target_id = conversation_id or self.thread_id
            return {"ok": True, "usage": get_conversation_usage(target_id)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_projects(self) -> dict:
        try:
            return {"ok": True, "projects": list_projects(self.current_project)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_history(self) -> dict:
        try:
            project = self._ensure_active_project()
            return {"ok": True, "history": self._history_snapshot(project)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_project(self, project_id: str = DEFAULT_PROJECT_ID) -> dict:
        try:
            self.current_project = open_project(project_id or DEFAULT_PROJECT_ID)
            self.thread_id = uuid4().hex
            self._reset_agent()
            return {
                "ok": True,
                "projects": list_projects(self.current_project),
                "context": self.get_context(),
                "history": self._history_snapshot(self.current_project),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def create_project(self, name: str | None = None, project_path: str | None = None) -> dict:
        try:
            self.current_project = create_map_project_at(name=name, project_path=project_path)
            self.thread_id = uuid4().hex
            self._reset_agent()
            return {
                "ok": True,
                "projects": list_projects(self.current_project),
                "context": self.get_context(),
                "history": self._history_snapshot(self.current_project),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def choose_project_directory(self, initial_path: str | None = None) -> dict:
        if self._window is None:
            return {"ok": False, "error": "窗口尚未就绪"}
        try:
            initial = Path(initial_path or PROJECTS_DIR).expanduser()
            directory = initial if initial.is_dir() else initial.parent
            selected = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=str(directory),
                allow_multiple=False,
            )
            if not selected:
                return {"ok": True, "cancelled": True}
            path = selected[0] if isinstance(selected, (list, tuple)) else selected
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_map_project_file(self, map_file_path: str | None = None) -> dict:
        try:
            selected_path = map_file_path
            if not selected_path:
                if self._window is None:
                    return {"ok": False, "error": "窗口尚未就绪"}
                selected = self._window.create_file_dialog(
                    webview.FOLDER_DIALOG,
                    directory=str(PROJECTS_DIR),
                    allow_multiple=False,
                )
                if not selected:
                    return {"ok": True, "cancelled": True}
                selected_path = selected[0] if isinstance(selected, (list, tuple)) else selected

            path = Path(str(selected_path)).expanduser().resolve(strict=False)
            if path.is_dir():
                self.current_project = open_map_project_from_directory(str(path))
            else:
                self.current_project = open_map_project_from_file(str(path))
            self.thread_id = uuid4().hex
            self._reset_agent()
            return {
                "ok": True,
                "projects": list_projects(self.current_project),
                "context": self.get_context(),
                "history": self._history_snapshot(self.current_project),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def remove_recent_project(self, project_id: str) -> dict:
        try:
            remove_recent_project(project_id)
            return {
                "ok": True,
                "projects": list_projects(self.current_project),
                "context": self.get_context(),
                "history": self._history_snapshot(self.current_project),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_project_files(self) -> dict:
        try:
            project = self._ensure_active_project()
            return {"ok": True, "tree": list_project_files(project)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def read_project_file(self, path: str) -> dict:
        try:
            project = self._ensure_active_project()
            return {"ok": True, "file": read_project_file(project, path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_project_file(self, path: str, content: str, encoding: str | None = None) -> dict:
        try:
            project = self._ensure_active_project()
            file_snapshot = save_project_file(project, path, content, encoding)
            return {"ok": True, "file": file_snapshot, "tree": list_project_files(project)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def create_project_item(self, parent_path: str | None, name: str, kind: str = "file") -> dict:
        try:
            project = self._ensure_active_project()
            result = create_project_item(project, parent_path, name, kind)
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def rename_project_item(self, path: str, new_name: str) -> dict:
        try:
            project = self._ensure_active_project()
            result = rename_project_item(project, path, new_name)
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_project_item(self, path: str) -> dict:
        try:
            project = self._ensure_active_project()
            result = delete_project_item(project, path)
            return {"ok": True, **result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_provider(self, provider: dict, original_name: str | None = None) -> dict:
        try:
            original_name = (original_name or provider.get("original_name") or "").strip()
            config = ProviderConfig(
                type=provider.get("type") or "openai-compatible",
                name=(provider.get("name") or "").strip(),
                base_url=(provider.get("base_url") or "").strip(),
                api_key=provider.get("api_key") or "",
            )
            if original_name:
                update_provider_config(original_name, config)
            else:
                add_provider_config(config)
            self._reset_agent()
            return {"ok": True, "settings": settings_snapshot(), "context": self.get_context()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_provider(self, provider_name: str) -> dict:
        try:
            remove_provider_config(provider_name)
            self._reset_agent()
            return {"ok": True, "settings": settings_snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def test_provider(self, provider_name: str) -> dict:
        try:
            result = test_provider_connection(provider_name)
            result["settings"] = settings_snapshot()
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def fetch_provider_models(self, provider_name: str) -> dict:
        try:
            models = fetch_available_models(provider_name)
            cache_provider_models(provider_name, models)
            return {
                "ok": True,
                "models": [model.model_dump() for model in models],
                "settings": settings_snapshot(),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def enable_provider_models(
        self,
        provider_name: str,
        model_names: list[str],
        available_models: list[dict] | None = None,
    ) -> dict:
        try:
            model_infos = [
                ModelInfo(
                    name=model.get("name") or "",
                    context_length=int(model.get("context_length") or 0),
                    max_tokens=int(model.get("max_tokens") or 0),
                    support_data_types=model.get("support_data_types") or ["text"],
                )
                for model in (available_models or [])
                if model.get("name")
            ]
            set_models_for_provider(provider_name, model_names, model_infos)
            self._reset_agent()
            return {"ok": True, "settings": settings_snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def save_model(self, model: dict) -> dict:
        try:
            config = ModelConfig(
                provider_name=model.get("provider_name") or "",
                name=model.get("name") or "",
                display_name=model.get("display_name") or model.get("name") or "",
                enabled=bool(model.get("enabled", True)),
                temperature=float(model.get("temperature", 0)),
                max_tokens=int(model.get("max_tokens") or 0),
                context_length=int(model.get("context_length") or 0),
                support_data_types=model.get("support_data_types") or ["text"],
                input_price_per_million=float(model.get("input_price_per_million") or 0),
                cached_input_price_per_million=float(
                    model.get("cached_input_price_per_million") or 0
                ),
                output_price_per_million=float(model.get("output_price_per_million") or 0),
                currency=(model.get("currency") or "CNY").upper(),
            )
            upsert_model_config(config)
            if model.get("active"):
                set_active_configured_model(config.provider_name, config.name)
            self._reset_agent()
            return {"ok": True, "settings": settings_snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_model(self, provider_name: str, model_name: str) -> dict:
        try:
            remove_model_config(provider_name, model_name)
            self._reset_agent()
            return {"ok": True, "settings": settings_snapshot()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_active_model(self, provider_name: str, model_name: str) -> dict:
        try:
            set_active_configured_model(provider_name, model_name)
            self._reset_agent()
            return {"ok": True, "settings": settings_snapshot(), "context": self.get_context()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def new_chat(self) -> dict:
        with self._runs_lock:
            if self._active_run_id:
                return {"ok": False, "error": "当前仍有运行中的任务，先中止或等待完成。"}
            self.thread_id = uuid4().hex
        project = self._ensure_active_project()
        return {
            "ok": True,
            "context": self.get_context(),
            "history": self._history_snapshot(project),
        }

    def open_chat(self, conversation_id: str) -> dict:
        try:
            with self._runs_lock:
                if self._active_run_id:
                    return {"ok": False, "error": "当前仍有运行中的任务，请先中止或等待完成。"}
            project = self._ensure_active_project()
            conversation = get_conversation(project, conversation_id)
            if conversation is None:
                return {"ok": False, "error": "对话记录不存在。"}
            self.thread_id = conversation["id"]
            return {
                "ok": True,
                "context": self.get_context(),
                "history": self._history_snapshot(project),
                "conversation": conversation,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_chat(self, conversation_id: str) -> dict:
        try:
            with self._runs_lock:
                if self._active_run_id:
                    return {"ok": False, "error": "当前仍有运行中的任务，请先中止或等待完成。"}
            project = self._ensure_active_project()
            deleted = delete_conversation(project, conversation_id)
            if self.thread_id == conversation_id:
                self.thread_id = uuid4().hex
            return {
                "ok": True,
                "deleted": deleted,
                "context": self.get_context(),
                "history": self._history_snapshot(project),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_run(self, text: str, options: dict | None = None) -> dict:
        prompt = (text or "").strip()
        if not prompt:
            return {"ok": False, "error": "请输入指令。"}
        project = self._ensure_active_project()

        with self._runs_lock:
            if self._active_run_id:
                return {"ok": False, "error": "已有任务正在运行。"}
            run_id = uuid4().hex
            state = RunState(run_id=run_id, thread_id=self.thread_id, project=project)
            try:
                active_model = get_active_model()
                if active_model:
                    state.provider_name, state.model_name = active_model
                    state.model_config = get_model_config(state.provider_name, state.model_name)
            except Exception:
                pass
            self._runs[run_id] = state
            self._active_run_id = run_id

        try:
            append_message(project, state.thread_id, "user", prompt)
        except Exception as exc:
            with self._runs_lock:
                self._runs.pop(run_id, None)
                if self._active_run_id == run_id:
                    self._active_run_id = None
            return {"ok": False, "error": str(exc)}

        worker = threading.Thread(
            target=self._run_worker,
            args=(state, prompt, options or {}),
            name=f"ra3-agent-{run_id[:8]}",
            daemon=True,
        )
        worker.start()
        return {"ok": True, "runId": run_id, "history": self._history_snapshot(project)}

    def poll_run(self, run_id: str, max_events: int = 80) -> dict:
        with self._runs_lock:
            state = self._runs.get(run_id)
        if state is None:
            return {"ok": False, "error": "运行记录不存在。"}

        events = []
        for _ in range(max_events):
            try:
                events.append(state.events.get_nowait())
            except Empty:
                break

        finished = state.status in {"done", "error", "cancelled"}
        if finished and not events:
            with self._runs_lock:
                self._runs.pop(run_id, None)

        return {
            "ok": True,
            "status": state.status,
            "events": events,
            "error": state.error,
            "elapsed": round(perf_counter() - state.started_at, 2),
        }

    def stop_run(self, run_id: str | None = None) -> dict:
        with self._runs_lock:
            state = self._runs.get(run_id or self._active_run_id or "")
        if state is None:
            return {"ok": False, "error": "没有正在运行的任务。"}
        state.cancel_requested.set()
        state.emit({"type": "status", "text": "已请求中止，等待当前响应片段结束。"})
        return {"ok": True}

    def _run_worker(self, state: RunState, prompt: str, options: dict) -> None:
        try:
            asyncio.run(self._run_agent(state, prompt, options))
        finally:
            with self._runs_lock:
                if self._active_run_id == state.run_id:
                    self._active_run_id = None

    async def _ensure_agent(self, state: RunState):
        if self.agent is not None:
            return self.agent

        state.emit({"type": "status", "text": "正在初始化 RA3 Agent..."})
        with self._agent_lock:
            needs_init = self.agent is None
        if needs_init:
            agent = await create_ra3_csharp_writer_agent()
            with self._agent_lock:
                self.agent = agent
        state.emit({"type": "status", "text": "Agent 已就绪。"})
        return self.agent

    def _save_assistant_message(self, state: RunState, status: str) -> None:
        project = state.project or self._ensure_active_project()
        content = state.assistant_text.strip()
        if not content and status == "cancelled":
            content = "本轮运行已中止。"
        if not content:
            return
        try:
            append_message(project, state.thread_id or self.thread_id, "assistant", content, status=status)
        except Exception as exc:
            state.emit({"type": "status", "text": f"保存对话历史失败：{exc}"})

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
            return record_usage_run(
                run_id=state.run_id,
                conversation_id=state.thread_id or self.thread_id,
                project=state.project or self._ensure_active_project(),
                provider_name=state.provider_name,
                model_name=state.model_name,
                status=status,
                usage=state.usage,
                cost=cost,
                currency=currency,
            )
        except Exception as exc:
            state.emit({"type": "status", "text": f"保存用量统计失败：{exc}"})
            return None

    def _done_event(self, state: RunState, status: str) -> dict:
        project = state.project or self._ensure_active_project()
        usage = self._record_usage(state, status)
        return {
            "type": "done",
            "status": status,
            "history": self._history_snapshot(project),
            "usage": usage,
        }

    async def _run_agent(self, state: RunState, prompt: str, options: dict) -> None:
        state.status = "running"
        state.emit(
            {
                "type": "run_started",
                "runId": state.run_id,
                "threadId": state.thread_id or self.thread_id,
                "permissionPolicy": options.get("permissionPolicy", "once"),
            }
        )

        tool_calls: dict[str, dict] = {}
        try:
            local_reply = _local_reply_for_prompt(prompt)
            if local_reply:
                state.usage = TokenUsage(usage_known=True)
                state.assistant_text += local_reply
                state.emit(
                    {
                        "type": "assistant_delta",
                        "messageId": "assistant",
                        "text": local_reply,
                    }
                )
                state.status = "done"
                self._save_assistant_message(state, "done")
                state.emit(self._done_event(state, "done"))
                return

            agent = await self._ensure_agent(state)
            config = {
                "configurable": {"thread_id": state.thread_id or self.thread_id},
                "run_name": "Ra3Copilot desktop conversation",
                "tags": ["ra3-copilot", "desktop"],
                "metadata": {
                    "app": APP_TITLE,
                    "thread_id": state.thread_id or self.thread_id,
                    "permission_policy": options.get("permissionPolicy", "once"),
                    "project_root": (state.project or self._ensure_active_project()).path,
                },
            }

            effective_prompt = _prompt_for_policy(
                prompt, options.get("permissionPolicy", "once")
            )
            async for chunk, _meta in agent.astream(
                {"messages": [HumanMessage(effective_prompt)]},
                config,
                stream_mode="messages",
            ):
                if state.cancel_requested.is_set():
                    state.status = "cancelled"
                    self._save_assistant_message(state, "cancelled")
                    state.emit(self._done_event(state, "cancelled"))
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
                                    "type": "tool_call",
                                    "tool": {
                                        "id": tool_id,
                                        "name": known_call["name"],
                                        "status": "running",
                                        "args": _decode_tool_args(known_call["args"]),
                                    },
                                }
                            )
                        if tool_call.get("args"):
                            known_call["args"] += tool_call["args"]

                    piece = _message_text(chunk)
                    if piece:
                        state.assistant_text += piece
                        state.emit(
                            {
                                "type": "assistant_delta",
                                "messageId": chunk.id or "assistant",
                                "text": piece,
                            }
                        )

                elif isinstance(chunk, ToolMessage):
                    tool_id = getattr(chunk, "tool_call_id", None) or getattr(
                        chunk, "name", None
                    ) or f"tool-{len(tool_calls)}"
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
                            "type": "tool_result",
                            "tool": {
                                "id": tool_id,
                                "name": getattr(chunk, "name", None) or known_call["name"],
                                "status": "completed",
                                "args": _decode_tool_args(known_call["args"]),
                                "result": _tool_result_text(chunk.content),
                                "elapsed": round(elapsed, 2),
                            },
                        }
                    )

            state.status = "done"
            self._save_assistant_message(state, "done")
            state.emit(self._done_event(state, "done"))
        except Exception as exc:
            trace = _exception_trace(exc)
            message = _exception_message(exc)
            state.status = "error"
            state.error = message
            error_text = f"运行出错：{message}"
            state.assistant_text = (
                f"{state.assistant_text.rstrip()}\n\n{error_text}"
                if state.assistant_text.strip()
                else error_text
            )
            self._save_assistant_message(state, "error")

            for tool_id, known_call in tool_calls.items():
                if known_call.get("status") == "completed":
                    continue
                known_call["status"] = "error"
                elapsed = perf_counter() - known_call["startedAt"]
                state.emit(
                    {
                        "type": "tool_result",
                        "tool": {
                            "id": tool_id,
                            "name": known_call.get("name") or tool_id,
                            "status": "error",
                            "args": _decode_tool_args(known_call.get("args", "")),
                            "result": f"{message}\n\n{trace}",
                            "elapsed": round(elapsed, 2),
                        },
                    }
                )

            state.emit(
                {
                    "type": "error",
                    "message": message,
                    "trace": trace,
                    "history": self._history_snapshot(state.project or self._ensure_active_project()),
                }
            )
            state.emit(self._done_event(state, "error"))


def run(debug: bool = False) -> None:
    load_runtime_env()
    index_path = _web_index_path()
    if not index_path.exists():
        raise FileNotFoundError(f"Desktop frontend not found: {index_path}")

    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

    bridge = DesktopBridge()
    window = webview.create_window(
        APP_TITLE,
        index_path.as_uri(),
        js_api=bridge,
        width=1280,
        height=820,
        min_size=(980, 640),
        resizable=True,
        frameless=True,
        easy_drag=False,
        text_select=True,
    )
    bridge.bind_window(window)
    webview.start(debug=debug)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Ra3Copilot desktop frontend.")
    parser.add_argument("--debug", action="store_true", help="Enable the webview debug mode.")
    args = parser.parse_args(argv)
    run(debug=args.debug)


if __name__ == "__main__":
    main()
