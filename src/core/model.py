from core.user_data.provider import provider_config_dict


def list_available_models(provider_name: str):
    if provider_name not in provider_config_dict:
        raise ValueError(f"Provider config not found: {provider_name}")