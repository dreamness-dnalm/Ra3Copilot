from core.user_data.config import get_active_model
from core.user_data.provider import provider_config_dict, list_available_models, ModelInfo
from langchain_openai import ChatOpenAI

def get_model():
    provider_name, model_name = get_active_model()

    provider_config = provider_config_dict[provider_name]
    if provider_config is None:
        raise ValueError(f"Provider config not found: {provider_name}")
    models = list_available_models(provider_name)
    model_info: ModelInfo | None = None
    for model in models:
        if model.name == model_name:
            model_info = model
            break
    if model_info is None:
        raise ValueError(f"Model not found: {model_name}")

    llm = ChatOpenAI(
        model=model_info.name,
        api_key=provider_config.api_key,
        base_url=provider_config.base_url,
    )
    return llm, provider_name, model_info