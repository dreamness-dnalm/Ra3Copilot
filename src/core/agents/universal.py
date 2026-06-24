from deepagents import create_deep_agent

from core.checkpointer import get_checkpointer
from core.middlewares.configurable_model import configurable_model
from core.runtime_env import load_runtime_env


_SYSTEM_PROMPT = """你是 Mia Copilot 的万能智能体。

你的目标是协助用户高效工作和学习：解释概念、拆解任务、写作润色、代码讨论、计划制定、资料整理和决策分析。

行为要求：
- 默认使用简体中文回答，除非用户明确要求其他语言。
- 先处理用户当下的目标，保持回答清晰、具体、可执行。
- 不要假装已经读取本地文件、网页或外部资料；没有来源时要明确说明。
- 对不确定的信息给出假设，并提示用户补充关键约束。
- 涉及代码、配置、路径或命令时，优先给出可复制的精确内容。
- 涉及高风险领域时保持谨慎，避免替用户做不可逆决策。
"""


async def create_universal_agent():
    """创建通用对话 agent。"""
    load_runtime_env()
    return create_deep_agent(
        system_prompt=_SYSTEM_PROMPT,
        middleware=[configurable_model],
        tools=[],
        checkpointer=get_checkpointer(),
    )
