from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from core.agents.project_skills import load_project_skills, resolve_project_root
from core.checkpointer import get_checkpointer
from core.middlewares.configurable_model import configurable_model
from core.middlewares.project_context import project_context
from core.runtime_env import load_runtime_env


_SYSTEM_PROMPT = """你是 Mia Copilot 的万能智能体。

你的目标是协助用户高效工作和学习：解释概念、拆解任务、写作润色、代码讨论、计划制定、资料整理和决策分析。

行为要求：
- 默认使用简体中文回答，除非用户明确要求其他语言。
- 先处理用户当下的目标，保持回答清晰、具体、可执行。
- 文件工具（write_file/read_file/edit_file/grep/glob/ls）直接操作当前工程目录，使用相对路径或以 / 开头的虚拟路径，路径会自动解析到工程根目录下。
- 对不确定的信息给出假设，并提示用户补充关键约束。
- 涉及代码、配置、路径或命令时，优先给出可复制的精确内容。
- 涉及高风险领域时保持谨慎，避免替用户做不可逆决策。
"""


def _load_system_prompt(project_path: str | None = None) -> str:
    project_skills = load_project_skills(project_path)
    if not project_skills:
        return _SYSTEM_PROMPT
    return f"{_SYSTEM_PROMPT}\n\n{project_skills}"


async def create_universal_agent(project_path: str | None = None):
    """创建通用对话 agent。

    ``project_path`` 用作文件工具 backend 的根目录，使 write/read/edit/grep
    等工具直接操作该工程目录。
    """
    load_runtime_env()
    project_root = resolve_project_root(project_path)
    backend = FilesystemBackend(root_dir=str(project_root), virtual_mode=True)
    return create_deep_agent(
        system_prompt=_load_system_prompt(str(project_root)),
        middleware=[configurable_model, project_context],
        tools=[],
        backend=backend,
        checkpointer=await get_checkpointer(),
    )
