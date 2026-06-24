from pathlib import Path

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver

from core.middlewares.configurable_model import configurable_model
from core.runtime_env import load_runtime_env
from core.tools.ra3_companion import load_ra3_companion_tools

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "agents" / "ra3_csharp_writer.md"
_SKILLS_ROOT = Path(__file__).resolve().parents[1] / "prompts" / "skills"
_SKILL_PATHS = sorted(_SKILLS_ROOT.glob("csharp/**/SKILL.md"))
_map_analyser_skill = _SKILLS_ROOT / "map-analyser" / "SKILL.md"
if _map_analyser_skill.is_file():
    _SKILL_PATHS.append(_map_analyser_skill)


def _load_system_prompt() -> str:
    parts = [_PROMPT_PATH.read_text(encoding="utf-8")]
    for path in _SKILL_PATHS:
        parts.append(f"\n\n## 参考资料：{path.parent.name}\n")
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


async def create_ra3_csharp_writer_agent():
    """创建 RA3 C# Writer agent"""
    load_runtime_env()
    tools = await load_ra3_companion_tools()
    return create_deep_agent(
        system_prompt=_load_system_prompt(),
        middleware=[configurable_model],
        tools=tools,
        checkpointer=InMemorySaver(),
    )