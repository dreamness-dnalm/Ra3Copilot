from langchain_core.callbacks import BaseCallbackHandler
import json
import sys


def _print_text(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


def _decode_json_like_string(text: str):
    stripped = text.strip()
    if not stripped:
        return text

    if stripped[0] not in "[{\"":
        return text

    try:
        return json.loads(text)
    except Exception:
        return text


def _normalize_for_print(obj):
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()

    if isinstance(obj, str):
        decoded = _decode_json_like_string(obj)
        if decoded is obj:
            return obj
        return _normalize_for_print(decoded)

    if isinstance(obj, dict):
        return {key: _normalize_for_print(value) for key, value in obj.items()}

    if isinstance(obj, list):
        return [_normalize_for_print(value) for value in obj]

    if isinstance(obj, tuple):
        return tuple(_normalize_for_print(value) for value in obj)

    return obj


def pretty_print(obj):
    obj = _normalize_for_print(obj)

    if isinstance(obj, (dict, list, tuple)):
        _print_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    else:
        _print_text(str(obj))


class DebugPrintCallbackHandler(BaseCallbackHandler):
    def on_chat_model_start(self, serialized, messages, **kwargs):
        _print_text("--------------LLM CONTEXT------------------")
        for batch in messages:
            for message in batch:
                _print_text("")
                pretty_print(message.type)
                pretty_print(message.content)
        _print_text("--------------LLM CONTEXT END------------------")