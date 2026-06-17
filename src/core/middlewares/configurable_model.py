from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from typing import Awaitable, Callable
from core.model import get_model


@wrap_model_call
async def configurable_model(request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]):
    model, provider_name, model_info = get_model()
    return await handler(request.override(model=model))