from langchain_mcp_adapters.client import MultiServerMCPClient

ALLOWED_TOOLS = {
    "run_ra3_c_sharp_script",
    "copy_ra3_map",
    "get_map_list",
    "get_lib_structure",
    "get_type_info",
    "get_method_signature",
}


async def load_ra3_companion_tools():
    client = MultiServerMCPClient(
        {
            "ra3_companion": {
                "transport": "http",
                "url": "http://127.0.0.1:30033/mcp",
            }
        }
    )
    tools = await client.get_tools()
    for tool in tools:
        print(tool.name, "-", tool.description)
    return [tool for tool in tools if tool.name in ALLOWED_TOOLS]
