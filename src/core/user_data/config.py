import json
import os
from copy import deepcopy

from core.user_data import user_data_path

config_file_path = os.path.join(user_data_path, 'config.json')
DEFAULT_LANGSMITH_ENDPOINT = "https://apac.api.smith.langchain.com"
DEFAULT_LANGSMITH_PROJECT = "ra3-copilot"

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
