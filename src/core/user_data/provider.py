import json
import os
from typing import Literal

from core.user_data import user_data_path
from pydantic import BaseModel, Field

config_file_path = os.path.join(user_data_path, 'config.json')

preset_provider_dict = {
    'deepseek': {
        'name': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'api_key': '',
    },
    # 'openai': {
    #     'name': 'OpenAI',
    #     'base_url': 'https://api.openai.com',
    #     'api_key': '',
    # },
    # 'minimax': {
    #     'name': 'MiniMax',
    #     'base_url': 'https://api.minimaxi.com',
    #     'api_key': '',
    # },
    # 'glm': {
    #     'name': 'GLM',
    #     'base_url': 'https://open.bigmodel.cn/api/paas/v4',
    #     'api_key': '',
    # },
    # 'openai-compatible': {
    #     'name': 'OpenAI Compatible',
    #     'base_url': '',
    #     'api_key': '',
    # },
}

provider_config_file_path = os.path.join(user_data_path, 'provider_config.json')

class ProviderConfig(BaseModel):
    type: Literal['deepseek', 'openai', 'minimax', 'glm', 'openai-compatible'] = Field(description="The type of the provider")
    name: str = Field(description="The name of the provider")
    base_url: str = Field(description="The base URL of the provider")
    api_key: str = Field(description="The API key of the provider")

provider_config_dict: dict[str, ProviderConfig] = {}

def reload_provider_config_dict():
    if not os.path.exists(provider_config_file_path):
        provider_config_dict.clear()
        return
    with open(provider_config_file_path, 'r') as f:
        data = json.load(f)
        _dict = {name: ProviderConfig(**config) for name, config in data.items()}
        provider_config_dict.clear()
        provider_config_dict.update(_dict)

reload_provider_config_dict()

def save_provider_config_dict():
    try:
        with open(provider_config_file_path, 'w') as f:
            json.dump(provider_config_dict, f, indent=4, default=lambda o: o.model_dump())
    except Exception as e:
        raise ValueError(f"Failed to save provider config: {e}")
    reload_provider_config_dict()


def add_provider_config(provider_config: ProviderConfig):
    reload_provider_config_dict()
    if provider_config.type not in preset_provider_dict:
        raise ValueError(f"Invalid provider type: {provider_config.type} (allowed types: {', '.join(preset_provider_dict.keys())})")
    provider_config_dict[provider_config.name] = provider_config
    save_provider_config_dict()

def remove_provider_config(provider_name: str):
    reload_provider_config_dict()
    if provider_name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {provider_name}")
    del provider_config_dict[provider_name]
    save_provider_config_dict()

def update_provider_config(provider_config: ProviderConfig):
    reload_provider_config_dict()
    if provider_config.name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {provider_config.name}")
    provider_config_dict[provider_config.name] = provider_config
    save_provider_config_dict()


class ModelInfo(BaseModel):
    name: str = Field(description="The name of the model")
    context_length: int = Field(description="The context length of the model")
    max_tokens: int = Field(description="The max tokens of the model")
    support_data_types: list[Literal['text', 'image', 'audio', 'video']] = Field(description="The data types supported by the model")

def list_available_models(provider_name: str):
    if provider_name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {provider_name}")
    provider_config = provider_config_dict[provider_name]
    if provider_config.type == 'deepseek':
        return [
            ModelInfo(name='deepseek-v4-flash', context_length=1000000, max_tokens=384000, support_data_types=['text']), 
            ModelInfo(name='deepseek-v4-pro', context_length=1000000, max_tokens=384000, support_data_types=['text'])
            ]
    elif provider_config.type == 'openai':
        raise ValueError(f"NOT IMPLEMENTED: list_available_models for openai-compatible provider")
    elif provider_config.type == 'minimax':
        raise ValueError(f"NOT IMPLEMENTED: list_available_models for openai-compatible provider")
    elif provider_config.type == 'glm':
        raise ValueError(f"NOT IMPLEMENTED: list_available_models for openai-compatible provider")
    elif provider_config.type == 'openai-compatible':
        raise ValueError(f"NOT IMPLEMENTED: list_available_models for openai-compatible provider")
    else:
        raise ValueError(f"Invalid provider type: {provider_config.type}")
