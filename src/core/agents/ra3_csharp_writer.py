from deepagents import create_deep_agent
from langgraph.checkpoint.memory import InMemorySaver

from core.middlewares.configurable_model import configurable_model
from core.tools.ra3_companion import load_ra3_companion_tools


async def create_ra3_csharp_writer_agent():
    """创建 RA3 C# Writer agent"""
    tools = await load_ra3_companion_tools()
    return create_deep_agent(
        middleware=[configurable_model],
        memory=['./prompts/agents/ra3_csharp_writer.md'],
        tools=tools,
        checkpointer=InMemorySaver(),
    )
