from core.user_data.config import get_active_model
from core.user_data.provider import get_model_config, get_provider_config
from langchain_openai import ChatOpenAI


def _normalize_base_url(base_url: str, provider_type: str) -> str:
    """Normalize the OpenAI base URL for local/compatible gateways.

    ``langchain-openai`` (via the openai SDK) appends ``/chat/completions`` to
    ``base_url`` directly, so it must already include the API version path. The
    preset providers (deepseek/openai/...) ship with a versioned URL, but
    ``openai-compatible`` entries — typically local servers like LM Studio at
    ``http://127.0.0.1:1234`` — are commonly configured without ``/v1``. Without
    it the request hits a wrong path and the stream returns no chunks
    ("No generations found in stream").

    Only append ``/v1`` for the openai-compatible kind when the URL has no path,
    so already-versioned URLs (including the presets) are left untouched.
    """
    if provider_type != "openai-compatible":
        return base_url
    url = (base_url or "").rstrip()
    if not url:
        return url
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    path = parts.path or ""
    # Root or empty path with no version segment -> add /v1.
    if path in ("", "/"):
        return urlunsplit((parts.scheme, parts.netloc, "/v1", parts.query, parts.fragment))
    return url


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
        "base_url": _normalize_base_url(provider_config.base_url, provider_config.type),
        "temperature": model_info.temperature,
        "stream_usage": True,
    }
    if model_info.max_tokens > 0:
        kwargs["max_tokens"] = model_info.max_tokens
    llm = ChatOpenAI(**kwargs)
    return llm, provider_name, model_info