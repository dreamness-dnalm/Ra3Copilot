import json
import os

from core.user_data import user_data_path

config_file_path = os.path.join(user_data_path, 'config.json')

if not os.path.exists(user_data_path):
    os.makedirs(user_data_path)

config_dict: dict = {}


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
