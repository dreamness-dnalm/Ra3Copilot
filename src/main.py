from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from core.context import Context
from core.mcp.ra3_companion import load_ra3_companion_tools
from core.callback.debug_print import DebugPrintCallbackHandler, pretty_print
import asyncio


async def main():
    context = Context()
    tools = await load_ra3_companion_tools()

    agent = create_agent(
        model=context.llm,
        tools=tools,
        system_prompt=f"""
你是 RA3 助手。
""",
    )
    req = "创建一个100x100的地图, 边界宽度为10, 可游玩区域为90x90, 高度为100, 纹理为BB_Gravel01, 地图名字为`agent_test_01`"
    # req = "我有哪些地图?"
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": req}]},
        config={"callbacks": [DebugPrintCallbackHandler()]},
    )
    pretty_print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
