from core.user_data.config import get_active_model
from core.user_data.provider import get_model_config, get_provider_config
from langchain_openai import ChatOpenAI

def get_model():
    active_model = get_active_model()
    if active_model is None:
        raise ValueError("No active model configured")

    provider_name, model_name = active_model
    provider_config = get_provider_config(provider_name)
    model_info = get_model_config(provider_name, model_name)
    if model_info is None:
        raise ValueError(f"Model not found: {model_name}")

    kwargs = {
        "model": model_info.name,
        "api_key": provider_config.api_key or "not-needed",
        "base_url": provider_config.base_url,
        "temperature": model_info.temperature,
        "stream_usage": True,
    }
    if model_info.max_tokens > 0:
        kwargs["max_tokens"] = model_info.max_tokens
    llm = ChatOpenAI(**kwargs)
    return llm, provider_name, model_info
