"""与 ra3_csharp_writer agent 交互的 TUI 聊天界面"""

import json
import traceback
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Markdown, Static

from core.agents.ra3_csharp_writer import create_ra3_csharp_writer_agent

MAX_TOOL_RESULT_PREVIEW = 500

RA3_BANNER = r"""
██████╗  █████╗ ██████╗      ██████╗ ██████╗ ██████╗ ██╗██╗      ██████╗ ████████╗
██╔══██╗██╔══██╗╚════██╗    ██╔════╝██╔═══██╗██╔══██╗██║██║     ██╔═══██╗╚══██╔══╝
██████╔╝███████║ █████╔╝    ██║     ██║   ██║██████╔╝██║██║     ██║   ██║   ██║
██╔══██╗██╔══██║ ╚═══██╗    ██║     ██║   ██║██╔═══╝ ██║██║     ██║   ██║   ██║
██║  ██║██║  ██║██████╔╝    ╚██████╗╚██████╔╝██║     ██║███████╗╚██████╔╝   ██║
╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝      ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝ ╚═════╝    ╚═╝
                         Red Alert 3 — C# Writer Agent
"""


def _message_text(message) -> str:
    """兼容 .text 是属性或方法的 langchain 版本"""
    text = message.text
    return text() if callable(text) else text


def _tool_result_preview(content) -> str:
    """提取工具返回的文本, 并还原 JSON 中的 \\uXXXX 转义以提高可读性"""
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
        text = json.dumps(json.loads(text), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass
    return text


class Ra3CopilotTUIApp(App):
    TITLE = "RA3 Copilot"
    SUB_TITLE = "C# Writer Agent"

    CSS = """
    #chat {
        padding: 1 2;
    }
    .user-msg {
        margin: 1 0 0 10;
        padding: 0 1;
        border: round $primary;
    }
    .ai-msg {
        margin: 1 10 0 0;
        padding: 0 1;
        border: round $success;
    }
    .tool-msg {
        color: $text-muted;
        margin: 0 0 0 2;
    }
    .info-msg {
        color: $text-muted;
        margin: 1 0 0 0;
        text-style: italic;
    }
    .error-msg {
        color: $text-error;
        margin: 1 0 0 0;
    }
    .banner {
        color: $error;
        width: auto;
    }
    #prompt {
        dock: bottom;
    }
    """

    BINDINGS = [
        ("ctrl+l", "clear_chat", "清空会话"),
    ]

    def __init__(self):
        super().__init__()
        self.agent = None
        self.thread_id = uuid4().hex

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="chat")
        yield Input(placeholder="正在初始化 agent...", id="prompt", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.show_banner()
        self.init_agent()

    @work
    async def show_banner(self) -> None:
        await self._append(Static(RA3_BANNER, classes="banner", markup=False))

    # ---------- 界面辅助 ----------

    async def _append(self, widget) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        await chat.mount(widget)
        chat.scroll_end(animate=False)

    async def _append_info(self, text: str) -> None:
        await self._append(Static(text, classes="info-msg"))

    async def _append_error(self, text: str) -> None:
        await self._append(Static(text, classes="error-msg"))

    def _set_input_enabled(self, enabled: bool, placeholder: str = "") -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = not enabled
        if placeholder:
            prompt.placeholder = placeholder
        if enabled:
            prompt.focus()

    # ---------- agent 初始化 ----------

    @work
    async def init_agent(self) -> None:
        try:
            self.agent = await create_ra3_csharp_writer_agent()
        except Exception as e:
            await self._append_error(
                f"Agent 初始化失败 (请确认 RA3 Companion MCP 服务已在 127.0.0.1:30033 启动):\n{e}"
            )
            self._set_input_enabled(True, "Agent 初始化失败, 输入 /quit 退出")
            return
        await self._append_info("Agent 已就绪, 输入消息开始对话。输入 /quit 退出, Ctrl+L 清空会话。")
        self._set_input_enabled(True, "输入消息, 回车发送...")

    # ---------- 交互 ----------

    @on(Input.Submitted, "#prompt")
    async def handle_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        if text.lower() in ("/quit", "/exit", "/q"):
            self.exit()
            return
        if self.agent is None:
            await self._append_error("Agent 未就绪, 仅支持 /quit 退出。")
            return
        await self._append(Static(f"你: {text}", classes="user-msg"))
        self.run_agent(text)

    @work(exclusive=True)
    async def run_agent(self, text: str) -> None:
        self._set_input_enabled(False, "Agent 思考中...")
        try:
            await self._stream_response(text)
        except Exception:
            await self._append_error(f"对话出错:\n{traceback.format_exc(limit=5)}")
        finally:
            self._set_input_enabled(True, "输入消息, 回车发送...")

    async def _stream_response(self, text: str) -> None:
        config = {"configurable": {"thread_id": self.thread_id}}
        current_md: Markdown | None = None
        current_id: str | None = None
        buffer = ""

        async for chunk, _meta in self.agent.astream(
            {"messages": [HumanMessage(text)]},
            config,
            stream_mode="messages",
        ):
            if isinstance(chunk, AIMessageChunk):
                # 显示工具调用 (名称只在第一个 chunk 中出现)
                for tc in chunk.tool_call_chunks or []:
                    if tc.get("name"):
                        await self._append(
                            Static(f"[调用工具] {tc['name']}", classes="tool-msg")
                        )
                        current_md = None

                piece = _message_text(chunk)
                if not piece:
                    continue
                # 新的 AI 消息开始时创建新气泡
                if current_md is None or chunk.id != current_id:
                    current_id = chunk.id
                    buffer = ""
                    current_md = Markdown("", classes="ai-msg")
                    await self._append(current_md)
                buffer += piece
                current_md.update(buffer)
                self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

            elif isinstance(chunk, ToolMessage):
                preview = _tool_result_preview(chunk.content).replace("\n", " ")
                if len(preview) > MAX_TOOL_RESULT_PREVIEW:
                    preview = preview[:MAX_TOOL_RESULT_PREVIEW] + "..."
                await self._append(
                    Static(f"[工具返回] {chunk.name}: {preview}", classes="tool-msg")
                )
                current_md = None

    # ---------- 快捷键 ----------

    async def action_clear_chat(self) -> None:
        self.thread_id = uuid4().hex
        await self.query_one("#chat", VerticalScroll).remove_children()
        await self._append_info("会话已清空。")


def run() -> None:
    Ra3CopilotTUIApp().run()
