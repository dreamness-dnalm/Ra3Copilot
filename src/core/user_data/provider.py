from __future__ import annotations

import json
import os
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from core.user_data import user_data_path
from core.user_data.config import clear_active_model, get_active_model, set_active_model


ProviderType = Literal[
    "deepseek",
    "openai",
    "openrouter",
    "nvidia",
    "minimax",
    "glm",
    "openai-compatible",
]
DataType = Literal["text", "image", "audio", "video"]

provider_config_file_path = os.path.join(user_data_path, "provider_config.json")
model_config_file_path = os.path.join(user_data_path, "model_config.json")

preset_provider_dict: dict[str, dict[str, str | bool]] = {
    "deepseek": {
        "type": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "description": "DeepSeek 官方 OpenAI 兼容接口",
        "requires_api_key": True,
    },
    "openai": {
        "type": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "description": "OpenAI 官方接口",
        "requires_api_key": True,
    },
    "openrouter": {
        "type": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "description": "OpenRouter 统一 OpenAI 兼容接口",
        "requires_api_key": True,
    },
    "nvidia": {
        "type": "nvidia",
        "name": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": "",
        "description": "NVIDIA API Catalog / NIM OpenAI 兼容接口",
        "requires_api_key": True,
    },
    "glm": {
        "type": "glm",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "description": "智谱 OpenAI 兼容接口",
        "requires_api_key": True,
    },
    "minimax": {
        "type": "minimax",
        "name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "api_key": "",
        "description": "MiniMax OpenAI 兼容接口",
        "requires_api_key": True,
    },
    "openai-compatible": {
        "type": "openai-compatible",
        "name": "OpenAI 兼容",
        "base_url": "",
        "api_key": "",
        "description": "本地模型、代理网关或第三方兼容接口",
        "requires_api_key": False,
    },
}


class ProviderConfig(BaseModel):
    type: ProviderType = Field(description="Provider implementation type")
    name: str = Field(description="Unique provider config name")
    base_url: str = Field(description="Provider base URL")
    api_key: str = Field(default="", description="Provider API key")


class ModelInfo(BaseModel):
    name: str = Field(description="Model name")
    context_length: int = Field(default=0, description="Context length")
    max_tokens: int = Field(default=0, description="Default max output tokens")
    support_data_types: list[DataType] = Field(default_factory=lambda: ["text"])


class ModelConfig(ModelInfo):
    provider_name: str = Field(description="Provider config name")
    display_name: str = Field(default="", description="User-visible model label")
    enabled: bool = Field(default=True, description="Whether this model is available")
    temperature: float = Field(default=0, ge=0, le=2)
    input_price_per_million: float = Field(default=0, ge=0)
    cached_input_price_per_million: float = Field(default=0, ge=0)
    output_price_per_million: float = Field(default=0, ge=0)
    currency: Literal["CNY", "USD"] = "CNY"


provider_config_dict: dict[str, ProviderConfig] = {}
model_config_dict: dict[str, ModelConfig] = {}


def _ensure_user_data_dir() -> None:
    if not os.path.exists(user_data_path):
        os.makedirs(user_data_path)


def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: str, data: dict) -> None:
    _ensure_user_data_dir()
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def _model_key(provider_name: str, model_name: str) -> str:
    return f"{provider_name}/{model_name}"


def _model_pricing_from_existing(existing: ModelConfig | None) -> dict:
    if existing is None:
        return {
            "input_price_per_million": 0,
            "cached_input_price_per_million": 0,
            "output_price_per_million": 0,
            "currency": "CNY",
        }
    return {
        "input_price_per_million": existing.input_price_per_million,
        "cached_input_price_per_million": existing.cached_input_price_per_million,
        "output_price_per_million": existing.output_price_per_million,
        "currency": existing.currency or "CNY",
    }


def reload_provider_config_dict() -> None:
    data = _read_json(provider_config_file_path)
    provider_config_dict.clear()
    provider_config_dict.update(
        {
            name: ProviderConfig(**config)
            for name, config in data.items()
        }
    )


def reload_model_config_dict() -> None:
    data = _read_json(model_config_file_path)
    model_config_dict.clear()
    model_config_dict.update(
        {
            key: ModelConfig(**config)
            for key, config in data.items()
        }
    )


def reload_all_config() -> None:
    reload_provider_config_dict()
    reload_model_config_dict()


def save_provider_config_dict() -> None:
    _write_json(
        provider_config_file_path,
        {
            name: config.model_dump()
            for name, config in provider_config_dict.items()
        },
    )
    reload_provider_config_dict()


def save_model_config_dict() -> None:
    _write_json(
        model_config_file_path,
        {
            key: config.model_dump()
            for key, config in model_config_dict.items()
        },
    )
    reload_model_config_dict()


def list_presets() -> list[dict]:
    return [
        {
            "id": key,
            **value,
        }
        for key, value in preset_provider_dict.items()
    ]


def list_provider_configs() -> list[ProviderConfig]:
    reload_provider_config_dict()
    return sorted(provider_config_dict.values(), key=lambda item: item.name.lower())


def get_provider_config(provider_name: str) -> ProviderConfig:
    reload_provider_config_dict()
    if provider_name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {provider_name}")
    return provider_config_dict[provider_name]


def _validate_provider_config(provider_config: ProviderConfig) -> None:
    if provider_config.type not in preset_provider_dict:
        raise ValueError(
            f"Invalid provider type: {provider_config.type} "
            f"(allowed types: {', '.join(preset_provider_dict.keys())})"
        )
    if not provider_config.name.strip():
        raise ValueError("Provider name is required")
    if provider_config.type != "openai-compatible" and not provider_config.base_url.strip():
        raise ValueError("Provider base_url is required")


def add_provider_config(provider_config: ProviderConfig) -> None:
    reload_provider_config_dict()
    _validate_provider_config(provider_config)
    if provider_config.name in provider_config_dict:
        raise ValueError(f"Provider name already exists: {provider_config.name}")
    provider_config_dict[provider_config.name] = provider_config
    save_provider_config_dict()


def update_provider_config(original_name: str, provider_config: ProviderConfig) -> None:
    reload_all_config()
    original_name = original_name.strip()
    if not original_name:
        raise ValueError("Original provider name is required")
    if original_name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {original_name}")

    _validate_provider_config(provider_config)
    new_name = provider_config.name
    if new_name != original_name and new_name in provider_config_dict:
        raise ValueError(f"Provider name already exists: {new_name}")

    del provider_config_dict[original_name]
    provider_config_dict[new_name] = provider_config

    if new_name != original_name:
        renamed_models: dict[str, ModelConfig] = {}
        for model in model_config_dict.values():
            if model.provider_name == original_name:
                model.provider_name = new_name
            renamed_models[_model_key(model.provider_name, model.name)] = model
        model_config_dict.clear()
        model_config_dict.update(renamed_models)

        active = get_active_model()
        if active and active[0] == original_name:
            set_active_model(new_name, active[1])

    save_provider_config_dict()
    save_model_config_dict()
    _repair_active_model()


def remove_provider_config(provider_name: str) -> None:
    reload_all_config()
    if provider_name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {provider_name}")
    del provider_config_dict[provider_name]

    removed_model_keys = [
        key for key, model in model_config_dict.items()
        if model.provider_name == provider_name
    ]
    for key in removed_model_keys:
        del model_config_dict[key]

    save_provider_config_dict()
    save_model_config_dict()
    _repair_active_model()


def list_model_configs(include_disabled: bool = True) -> list[ModelConfig]:
    reload_model_config_dict()
    models = list(model_config_dict.values())
    if not include_disabled:
        models = [model for model in models if model.enabled]
    return sorted(models, key=lambda item: (item.provider_name.lower(), item.name.lower()))


def get_model_config(provider_name: str, model_name: str) -> ModelConfig | None:
    reload_model_config_dict()
    return model_config_dict.get(_model_key(provider_name, model_name))


def upsert_model_config(model_config: ModelConfig) -> None:
    reload_all_config()
    if model_config.provider_name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {model_config.provider_name}")
    if not model_config.name.strip():
        raise ValueError("Model name is required")
    model_config.display_name = model_config.display_name or model_config.name
    model_config_dict[_model_key(model_config.provider_name, model_config.name)] = model_config
    save_model_config_dict()
    _repair_active_model()


def remove_model_config(provider_name: str, model_name: str) -> None:
    reload_model_config_dict()
    key = _model_key(provider_name, model_name)
    if key not in model_config_dict:
        raise ValueError(f"Model config not found: {key}")
    del model_config_dict[key]
    save_model_config_dict()
    _repair_active_model()


def cache_provider_models(
    provider_name: str,
    models: list[ModelInfo],
    *,
    default_enabled: bool = False,
) -> list[ModelConfig]:
    provider = get_provider_config(provider_name)
    reload_model_config_dict()
    cached: list[ModelConfig] = []

    for info in models:
        existing = model_config_dict.get(_model_key(provider.name, info.name))
        model_config = ModelConfig(
            provider_name=provider.name,
            name=info.name,
            display_name=(existing.display_name if existing else "") or info.name,
            enabled=existing.enabled if existing else default_enabled,
            temperature=existing.temperature if existing else 0,
            context_length=info.context_length or (existing.context_length if existing else 0),
            max_tokens=info.max_tokens or (existing.max_tokens if existing else 0),
            support_data_types=info.support_data_types or ["text"],
            **_model_pricing_from_existing(existing),
        )
        model_config_dict[_model_key(provider.name, info.name)] = model_config
        cached.append(model_config)

    save_model_config_dict()
    _repair_active_model()
    return cached


def set_models_for_provider(
    provider_name: str,
    model_names: list[str],
    available_models: list[ModelInfo] | None = None,
) -> list[ModelConfig]:
    """Enable exactly the named models for a provider.

    Only the selected models are upserted (enabled=True); models the user did
    not check are left completely untouched — they are neither added, deleted,
    nor disabled. This keeps pre-existing model configurations intact while
    letting the caller add models that may not be in the fetched list.
    """
    provider = get_provider_config(provider_name)
    available = {model.name: model for model in (available_models or [])}
    selected: list[ModelConfig] = []
    reload_model_config_dict()

    for name in model_names:
        info = available.get(name) or ModelInfo(name=name)
        existing = model_config_dict.get(_model_key(provider.name, info.name))
        model_config = ModelConfig(
            provider_name=provider.name,
            name=info.name,
            display_name=(existing.display_name if existing else "") or info.name,
            enabled=True,
            temperature=existing.temperature if existing else 0,
            context_length=info.context_length or (existing.context_length if existing else 0),
            max_tokens=info.max_tokens or (existing.max_tokens if existing else 0),
            support_data_types=info.support_data_types or ["text"],
            **_model_pricing_from_existing(existing),
        )
        model_config_dict[_model_key(provider.name, info.name)] = model_config
        selected.append(model_config)

    save_model_config_dict()
    _repair_active_model()
    return selected


def set_active_configured_model(provider_name: str, model_name: str) -> None:
    model_config = get_model_config(provider_name, model_name)
    if model_config is None:
        raise ValueError(f"Model config not found: {provider_name}/{model_name}")
    if not model_config.enabled:
        model_config.enabled = True
        upsert_model_config(model_config)
    set_active_model(provider_name, model_name)


def _repair_active_model() -> None:
    active_model = get_active_model()
    enabled = list_model_configs(include_disabled=False)
    if not enabled:
        clear_active_model()
        return
    if active_model is None:
        first = enabled[0]
        set_active_model(first.provider_name, first.name)
        return
    provider_name, model_name = active_model
    current = get_model_config(provider_name, model_name)
    if current is None or not current.enabled:
        first = enabled[0]
        set_active_model(first.provider_name, first.name)


def _model_endpoint_candidates(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    if not base:
        return []
    candidates = [f"{base}/models"]
    if not base.endswith("/v1"):
        candidates.append(f"{base}/v1/models")
    return candidates


def _parse_model_payload(payload) -> list[ModelInfo]:
    raw_models = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_models, list):
        return []

    models: list[ModelInfo] = []
    seen: set[str] = set()
    for item in raw_models:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or "").strip()
        else:
            name = ""
        if not name or name in seen:
            continue
        seen.add(name)
        models.append(ModelInfo(name=name, support_data_types=["text"]))
    return sorted(models, key=lambda model: model.name.lower())


def fetch_available_models(provider_name: str) -> list[ModelInfo]:
    provider = get_provider_config(provider_name)
    headers = {"Accept": "application/json"}
    if provider.api_key.strip():
        headers["Authorization"] = f"Bearer {provider.api_key.strip()}"

    errors: list[str] = []
    with httpx.Client(timeout=18) as client:
        for endpoint in _model_endpoint_candidates(provider.base_url):
            try:
                response = client.get(endpoint, headers=headers)
                if response.status_code in {404, 405}:
                    errors.append(f"{endpoint}: HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                models = _parse_model_payload(response.json())
                if models:
                    return models
                errors.append(f"{endpoint}: 未返回模型列表")
            except Exception as exc:
                errors.append(f"{endpoint}: {exc}")

    if provider.type == "deepseek":
        return [
            ModelInfo(name="deepseek-chat", context_length=64000, max_tokens=8192),
            ModelInfo(name="deepseek-reasoner", context_length=64000, max_tokens=8192),
        ]
    raise ValueError("无法拉取模型列表：" + "；".join(errors))


def test_provider_connection(provider_name: str) -> dict:
    models = fetch_available_models(provider_name)
    cache_provider_models(provider_name, models)
    return {
        "ok": True,
        "message": f"连接成功，发现 {len(models)} 个模型。",
        "models": [model.model_dump() for model in models],
    }


def settings_snapshot() -> dict:
    reload_all_config()
    active = get_active_model()
    return {
        "presets": list_presets(),
        "providers": [
            provider.model_dump()
            for provider in list_provider_configs()
        ],
        "models": [
            model.model_dump()
            for model in list_model_configs(include_disabled=True)
        ],
        "activeModel": (
            {"provider_name": active[0], "name": active[1]}
            if active
            else None
        ),
    }


reload_all_config()
