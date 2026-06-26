import json
import os
from copy import deepcopy
from uuid import uuid4

from core.user_data import user_data_path

config_file_path = os.path.join(user_data_path, 'config.json')
DEFAULT_LANGSMITH_ENDPOINT = "https://apac.api.smith.langchain.com"
DEFAULT_LANGSMITH_PROJECT = "ra3-copilot"
BUILTIN_SOUL_PRESETS = [
    {
        "id": "builtin-ra3-game-expert",
        "name": "RA3游戏专家",
        "content": (
            "你是熟悉《红色警戒3》地图、脚本、阵营机制和玩家体验的游戏开发专家。\n"
            "你会优先从可玩性、关卡节奏、触发器可靠性、地图资源与调试路径出发给建议。\n"
            "回答时保持专业、直接，必要时给出可落地的检查清单和修改步骤。"
        ),
        "builtin": True,
    },
    {
        "id": "builtin-reliable-assistant",
        "name": "可靠助理",
        "content": (
            "你是可靠、稳健、重视事实和执行质量的个人助理。\n"
            "你会先澄清目标和约束，再给出清晰可执行的方案。\n"
            "当信息不足时明确说明假设；当任务复杂时拆成小步推进。"
        ),
        "builtin": True,
    },
    {
        "id": "builtin-moe-catgirl",
        "name": "萌萌猫娘",
        "content": (
            "你是活泼、亲切、略带可爱语气的助理，但仍然以完成任务为第一优先级。\n"
            "你可以用轻松温柔的措辞回应用户，同时保持答案准确、清楚、可执行。\n"
            "涉及严肃、技术或高风险问题时收起玩笑，优先给出可靠建议。"
        ),
        "builtin": True,
    },
]
BUILTIN_SOUL_PRESET_IDS = {preset["id"] for preset in BUILTIN_SOUL_PRESETS}

if not os.path.exists(user_data_path):
    os.makedirs(user_data_path)

config_dict: dict = {}


def _default_observability_config() -> dict:
    return {
        "enabled": False,
        "langsmith_endpoint": DEFAULT_LANGSMITH_ENDPOINT,
        "langsmith_api_key": "",
        "langsmith_project": DEFAULT_LANGSMITH_PROJECT,
    }


def _default_assistant_config() -> dict:
    return {
        "qq_bot_enabled": False,
        "app_id": "",
        "app_secret": "",
    }


def reload_config_dict():
    if not os.path.exists(config_file_path):
        config_dict.clear()
        return
    with open(config_file_path, 'r', encoding='utf-8') as f:
        config_dict.clear()
        config_dict.update(json.load(f))

def save_config_dict():
    try:
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
    except Exception as e:
        raise ValueError(f"Failed to save config: {e}")

def get_active_model():
    reload_config_dict()
    if 'active_model' not in config_dict:
        return None
    active_model = config_dict['active_model']
    provider_name, model_name = active_model.split('/', 1)
    return provider_name, model_name

def set_active_model(provider_name: str, model_name: str):
    reload_config_dict()
    config_dict['active_model'] = f"{provider_name}/{model_name}"
    save_config_dict()

def clear_active_model():
    reload_config_dict()
    config_dict.pop('active_model', None)
    save_config_dict()


def normalize_observability_config(value: dict | None = None) -> dict:
    config = _default_observability_config()
    if isinstance(value, dict):
        config.update(
            {
                "enabled": bool(value.get("enabled", False)),
                "langsmith_endpoint": str(value.get("langsmith_endpoint") or value.get("endpoint") or config["langsmith_endpoint"]).strip(),
                "langsmith_api_key": str(value.get("langsmith_api_key") or value.get("api_key") or "").strip(),
                "langsmith_project": str(value.get("langsmith_project") or value.get("project") or config["langsmith_project"]).strip(),
            }
        )
    if not config["langsmith_endpoint"]:
        config["langsmith_endpoint"] = DEFAULT_LANGSMITH_ENDPOINT
    if not config["langsmith_project"]:
        config["langsmith_project"] = DEFAULT_LANGSMITH_PROJECT
    return config


def get_observability_config() -> dict:
    reload_config_dict()
    return normalize_observability_config(config_dict.get("observability"))


def _set_env_pair(langsmith_key: str, langchain_key: str, value: str) -> None:
    if value:
        os.environ[langsmith_key] = value
        os.environ[langchain_key] = value
    else:
        os.environ.pop(langsmith_key, None)
        os.environ.pop(langchain_key, None)


def apply_observability_env(config: dict | None = None) -> dict:
    observability = normalize_observability_config(config if config is not None else get_observability_config())
    tracing_value = "true" if observability["enabled"] else "false"
    os.environ["LANGSMITH_TRACING"] = tracing_value
    os.environ["LANGCHAIN_TRACING_V2"] = tracing_value
    _set_env_pair("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT", observability["langsmith_endpoint"])
    _set_env_pair("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", observability["langsmith_api_key"])
    _set_env_pair("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT", observability["langsmith_project"])
    return observability


def set_observability_config(value: dict) -> dict:
    reload_config_dict()
    observability = normalize_observability_config(value)
    config_dict["observability"] = deepcopy(observability)
    save_config_dict()
    apply_observability_env(observability)
    return observability


def normalize_assistant_config(value: dict | None = None) -> dict:
    config = _default_assistant_config()
    if isinstance(value, dict):
        config.update(
            {
                "qq_bot_enabled": bool(value.get("qq_bot_enabled", value.get("enabled", False))),
                "app_id": str(value.get("app_id") or value.get("appId") or value.get("appid") or "").strip(),
                "app_secret": str(value.get("app_secret") or value.get("appSecret") or value.get("secret") or "").strip(),
            }
        )
    return config


def get_assistant_config() -> dict:
    reload_config_dict()
    return normalize_assistant_config(config_dict.get("assistant"))


def set_assistant_config(value: dict) -> dict:
    reload_config_dict()
    assistant = normalize_assistant_config(value)
    config_dict["assistant"] = deepcopy(assistant)
    save_config_dict()
    return assistant


def _normalize_soul_preset(value: dict, *, builtin: bool = False) -> dict | None:
    if not isinstance(value, dict):
        return None
    preset_id = str(value.get("id") or "").strip()
    name = str(value.get("name") or "").strip()
    content = str(value.get("content") or "").strip()
    if not name:
        return None
    if not preset_id:
        preset_id = f"custom-{uuid4().hex[:12]}"
    return {
        "id": preset_id,
        "name": name,
        "content": content,
        "builtin": bool(builtin),
    }


def get_soul_presets() -> list[dict]:
    reload_config_dict()
    custom_presets = []
    for item in config_dict.get("soul_presets") or []:
        preset = _normalize_soul_preset(item, builtin=False)
        if preset and preset["id"] not in BUILTIN_SOUL_PRESET_IDS:
            custom_presets.append(preset)
    return deepcopy(BUILTIN_SOUL_PRESETS + custom_presets)


def get_soul_preset(preset_id: str | None) -> dict | None:
    target = str(preset_id or "").strip()
    if not target:
        return None
    for preset in get_soul_presets():
        if preset["id"] == target:
            return preset
    return None


def save_soul_preset(value: dict, original_id: str | None = None) -> dict:
    reload_config_dict()
    original = str(original_id or value.get("original_id") or "").strip()
    if original in BUILTIN_SOUL_PRESET_IDS:
        raise ValueError("内置 SOUL 预设不可修改")

    preset = _normalize_soul_preset(value, builtin=False)
    if not preset:
        raise ValueError("SOUL 预设名称不能为空")
    if preset["id"] in BUILTIN_SOUL_PRESET_IDS:
        raise ValueError("不能覆盖内置 SOUL 预设")
    if original:
        preset["id"] = original

    custom_presets = []
    replaced = False
    for item in config_dict.get("soul_presets") or []:
        existing = _normalize_soul_preset(item, builtin=False)
        if not existing or existing["id"] in BUILTIN_SOUL_PRESET_IDS:
            continue
        if existing["id"] == preset["id"]:
            custom_presets.append(preset)
            replaced = True
        else:
            custom_presets.append(existing)

    if not replaced:
        custom_presets.append(preset)

    config_dict["soul_presets"] = custom_presets
    save_config_dict()
    return deepcopy(preset)


def delete_soul_preset(preset_id: str) -> None:
    reload_config_dict()
    target = str(preset_id or "").strip()
    if target in BUILTIN_SOUL_PRESET_IDS:
        raise ValueError("内置 SOUL 预设不可删除")
    custom_presets = []
    for item in config_dict.get("soul_presets") or []:
        preset = _normalize_soul_preset(item, builtin=False)
        if preset and preset["id"] != target and preset["id"] not in BUILTIN_SOUL_PRESET_IDS:
            custom_presets.append(preset)
    config_dict["soul_presets"] = custom_presets
    save_config_dict()
