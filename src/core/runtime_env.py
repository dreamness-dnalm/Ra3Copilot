from __future__ import annotations

import os
from pathlib import Path

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_PLACEHOLDER_MARKERS = ("<", "your-api-key", "changeme", "replace-me")
_ENV_LOADED = False


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            if index == 0 or value[index - 1].isspace():
                return value[:index].rstrip()
    return value.strip()


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()
    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = _strip_inline_comment(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _load_env_file(path: Path, protected_keys: set[str]) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if key in protected_keys:
            continue
        os.environ[key] = value


def _env_paths() -> list[Path]:
    src_root = Path(__file__).resolve().parents[1]
    project_root = src_root.parent
    roots = []
    for root in (project_root, src_root, Path.cwd()):
        if root not in roots:
            roots.append(root)

    paths: list[Path] = []
    for root in roots:
        paths.extend((root / ".env", root / ".env.local"))
    return paths


def _apply_langsmith_compat() -> None:
    mapping = {
        "LANGSMITH_TRACING": "LANGCHAIN_TRACING_V2",
        "LANGSMITH_ENDPOINT": "LANGCHAIN_ENDPOINT",
        "LANGSMITH_API_KEY": "LANGCHAIN_API_KEY",
        "LANGSMITH_PROJECT": "LANGCHAIN_PROJECT",
    }
    for source, target in mapping.items():
        value = os.environ.get(source)
        if value and target not in os.environ:
            os.environ[target] = value


def load_runtime_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    protected_keys = set(os.environ)
    for path in _env_paths():
        _load_env_file(path, protected_keys)
    _apply_langsmith_compat()
    _ENV_LOADED = True


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return False


def _is_placeholder_secret(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.strip().lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def get_langsmith_status() -> dict[str, str | bool]:
    load_runtime_env()
    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    tracing = _env_bool("LANGSMITH_TRACING") or _env_bool("LANGCHAIN_TRACING_V2")
    placeholder = _is_placeholder_secret(api_key)
    if api_key and not placeholder:
        api_key_state = "configured"
    elif placeholder:
        api_key_state = "placeholder"
    else:
        api_key_state = "missing"

    return {
        "tracing": tracing,
        "endpoint": os.environ.get("LANGSMITH_ENDPOINT")
        or os.environ.get("LANGCHAIN_ENDPOINT")
        or "",
        "project": os.environ.get("LANGSMITH_PROJECT")
        or os.environ.get("LANGCHAIN_PROJECT")
        or "",
        "apiKeyState": api_key_state,
    }