from langchain.agents import create_agent
from langchain.chat_models import init_chat_model


def create_deepseek_agent(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
):
    model_kwargs = {}
    if base_url:
        model_kwargs["base_url"] = base_url
    if api_key:
        model_kwargs["api_key"] = api_key

    model = init_chat_model(
        "deepseek-chat",
        model_provider="deepseek",
        **model_kwargs,
    )
    return create_agent(
        model=model,
        tools=[],
        system_prompt="You are a helpful assistant.",
    )
