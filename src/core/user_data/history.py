from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


AGENT_DIR_NAME = ".agent"
HISTORY_DIR_NAME = "history"
DEFAULT_TITLE = "新对话"
MAX_TITLE_CHARS = 32
_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_segment(value: str) -> str:
    text = str(value or "").strip()
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", text)
    slug = re.sub(r"\s+", "-", slug).strip(".- ")
    slug = slug[:72] or "item"
    return f"{slug}-{digest}"


def _project_snapshot(project) -> dict:
    if hasattr(project, "model_dump"):
        return project.model_dump()
    return dict(project or {})


def _history_dir(project) -> Path:
    project_data = _project_snapshot(project)
    project_path = str(project_data.get("path") or "").strip()
    if not project_path:
        raise ValueError("项目路径不能为空")
    return Path(project_path).expanduser().resolve(strict=False) / AGENT_DIR_NAME / HISTORY_DIR_NAME


def _conversation_path(project, conversation_id: str) -> Path:
    return _history_dir(project) / f"{_safe_segment(conversation_id)}.json"


def _title_from_text(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return DEFAULT_TITLE
    if len(compact) > MAX_TITLE_CHARS:
        return f"{compact[:MAX_TITLE_CHARS]}..."
    return compact


def _read_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _new_conversation(project, conversation_id: str) -> dict:
    now = _now_iso()
    project_data = _project_snapshot(project)
    return {
        "id": conversation_id,
        "project_id": project_data.get("id") or "",
        "project_name": project_data.get("name") or "",
        "title": DEFAULT_TITLE,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def _normalize_conversation(data: dict, project_id: str, conversation_id: str | None = None) -> dict:
    messages = data.get("messages")
    if not isinstance(messages, list):
        messages = []
    normalized = {
        "id": str(data.get("id") or conversation_id or ""),
        "project_id": str(data.get("project_id") or project_id),
        "project_name": str(data.get("project_name") or ""),
        "title": str(data.get("title") or DEFAULT_TITLE),
        "created_at": str(data.get("created_at") or data.get("updated_at") or _now_iso()),
        "updated_at": str(data.get("updated_at") or data.get("created_at") or _now_iso()),
        "messages": [message for message in messages if isinstance(message, dict)],
    }
    return normalized


def _summary(conversation: dict) -> dict:
    messages = conversation.get("messages") or []
    last_message = next((message for message in reversed(messages) if message.get("content")), None)
    return {
        "id": conversation.get("id") or "",
        "project_id": conversation.get("project_id") or "",
        "project_name": conversation.get("project_name") or "",
        "title": conversation.get("title") or DEFAULT_TITLE,
        "created_at": conversation.get("created_at") or "",
        "updated_at": conversation.get("updated_at") or "",
        "message_count": len(messages),
        "last_message": {
            "role": last_message.get("role") if last_message else "",
            "content": last_message.get("content") if last_message else "",
            "created_at": last_message.get("created_at") if last_message else "",
        },
    }


def list_conversations(project) -> list[dict]:
    with _LOCK:
        project_data = _project_snapshot(project)
        project_id = str(project_data.get("id") or "")
        directory = _history_dir(project_data)
        if not directory.exists():
            return []

        conversations: list[dict] = []
        for path in directory.glob("*.json"):
            data = _read_json(path)
            if not data:
                continue
            conversation = _normalize_conversation(data, project_id)
            if conversation.get("messages"):
                conversations.append(_summary(conversation))

        conversations.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return conversations


def get_conversation(project, conversation_id: str) -> dict | None:
    with _LOCK:
        project_data = _project_snapshot(project)
        project_id = str(project_data.get("id") or "")
        path = _conversation_path(project_data, conversation_id)
        data = _read_json(path)
        if not data:
            return None
        return _normalize_conversation(data, project_id, conversation_id)


def delete_conversation(project, conversation_id: str) -> bool:
    with _LOCK:
        path = _conversation_path(project, conversation_id)
        if not path.exists():
            return False
        path.unlink()
        return True


def append_message(
    project,
    conversation_id: str,
    role: str,
    content: str,
    status: str | None = None,
) -> dict:
    text = str(content or "")
    if not text:
        raise ValueError("消息内容不能为空")

    project_data = _project_snapshot(project)
    project_id = str(project_data.get("id") or "")
    if not project_id:
        raise ValueError("项目 ID 不能为空")
    if not conversation_id:
        raise ValueError("对话 ID 不能为空")

    with _LOCK:
        path = _conversation_path(project_data, conversation_id)
        conversation = _read_json(path)
        if conversation:
            conversation = _normalize_conversation(conversation, project_id, conversation_id)
        else:
            conversation = _new_conversation(project_data, conversation_id)

        now = _now_iso()
        conversation["project_id"] = project_id
        conversation["project_name"] = project_data.get("name") or conversation.get("project_name") or ""
        conversation["updated_at"] = now
        if role == "user" and (
            not conversation.get("messages") or conversation.get("title") == DEFAULT_TITLE
        ):
            conversation["title"] = _title_from_text(text)

        message = {
            "id": uuid4().hex,
            "role": role,
            "content": text,
            "created_at": now,
        }
        if status:
            message["status"] = status
        conversation.setdefault("messages", []).append(message)
        _write_json(path, conversation)
        return conversation
