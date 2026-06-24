from __future__ import annotations

import json
from pathlib import Path

import httpx
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient

RA3_COMPANION_BASE_URL = "http://127.0.0.1:30033"
ANALYSER_CS_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "skills"
    / "map-analyser"
    / "references"
    / "analyser.cs"
)

ALLOWED_TOOLS = {
    "run_ra3_csharp_script",
    "copy_ra3_map",
    "get_map_list",
    "get_lib_structure",
    "get_type_info",
    "get_method_signature",
}


def _normalize_map_name(map_name: str) -> str:
    text = str(map_name or "").strip().strip("`\"'")
    if not text:
        raise ValueError("map_name is required")
    text = text.replace("\\", "/").rstrip("/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if text.lower().endswith(".map"):
        text = text[:-4]
    return text


def _format_runner_response(payload) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False, indent=2)

    data = payload.get("data")
    if isinstance(data, dict):
        output = data.get("output")
        error = data.get("error")
        if output:
            return str(output)
        if error:
            return f"地图分析失败：{error}"

    output = payload.get("output")
    error = payload.get("error") or payload.get("message")
    if output:
        return str(output)
    if error:
        return f"地图分析失败：{error}"
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("analyse_ra3_map")
def analyse_ra3_map(map_name: str) -> str:
    """使用 map-analyser skill 分析 RA3 地图资源分布、出生点、油井、观测站、矿脉和推荐矿场位置。"""
    return analyse_ra3_map_text(map_name)


def analyse_ra3_map_text(map_name: str) -> str:
    """Run the bundled map analyser script and return the raw textual result."""
    normalized_name = _normalize_map_name(map_name)
    if not ANALYSER_CS_PATH.is_file():
        raise FileNotFoundError(f"analyser.cs not found: {ANALYSER_CS_PATH}")

    code = ANALYSER_CS_PATH.read_text(encoding="utf-8").replace("###MAP_NAME###", normalized_name)
    with httpx.Client(timeout=90) as client:
        response = client.post(
            f"{RA3_COMPANION_BASE_URL}/api/csharpscript/run/code",
            json={"code": code},
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return response.text
    return _format_runner_response(payload)


async def load_ra3_companion_tools():
    local_tools = [analyse_ra3_map]
    client = MultiServerMCPClient(
        {
            "ra3_companion": {
                "transport": "http",
                "url": "http://127.0.0.1:30033/mcp",
            }
        }
    )
    try:
        tools = await client.get_tools()
    except Exception:
        return local_tools
    return local_tools + [tool for tool in tools if tool.name in ALLOWED_TOOLS]
