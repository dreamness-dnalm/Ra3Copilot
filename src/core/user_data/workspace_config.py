from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from core.user_data.config import get_soul_preset


AGENT_DIR_NAME = ".agent"
WORKSPACE_CONFIG_FILE = "workspace_config.json"
SOUL_FILE_NAME = "SOUL.md"
MANUAL_SOUL_PRESET_ID = "__manual__"


def _default_workspace_config() -> dict:
    return {
        "soul_preset_id": "",
        "im_integrations": {
            "qq": [],
        },
    }


def workspace_config_path(project) -> Path:
    project_path = str(_project_snapshot(project).get("path") or "").strip()
    if not project_path:
        raise ValueError("项目路径不能为空")
    return (
        Path(project_path).expanduser().resolve(strict=False)
        / AGENT_DIR_NAME
        / WORKSPACE_CONFIG_FILE
    )


def get_workspace_config(project) -> dict:
    path = workspace_config_path(project)
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        data = {}
    config = normalize_workspace_config(data if isinstance(data, dict) else {})
    if not config.get("soul_preset_id") and soul_file_path(project).is_file():
        config["soul_preset_id"] = MANUAL_SOUL_PRESET_ID
    return config


def set_workspace_config(project, value: dict | None) -> dict:
    config = normalize_workspace_config(value)
    path = workspace_config_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
    return deepcopy(config)


def normalize_workspace_config(value: dict | None = None) -> dict:
    config = _default_workspace_config()
    if not isinstance(value, dict):
        return config

    soul_preset_id = (
        value.get("soul_preset_id")
        or value.get("soulPresetId")
        or (value.get("soul") or {}).get("preset_id")
        or (value.get("soul") or {}).get("presetId")
        or ""
    )
    config["soul_preset_id"] = str(soul_preset_id).strip()

    im_integrations = value.get("im_integrations") or value.get("imIntegrations") or {}
    if not isinstance(im_integrations, dict):
        im_integrations = {}

    raw_bots = (
        im_integrations.get("qq")
        or value.get("qq_bots")
        or value.get("qqBots")
        or value.get("qq_bot_bindings")
        or []
    )
    if isinstance(raw_bots, dict):
        raw_bots = [raw_bots]

    bots = []
    if isinstance(raw_bots, list):
        for item in raw_bots:
            if not isinstance(item, dict):
                continue
            app_id = str(item.get("app_id") or item.get("appId") or item.get("appid") or "").strip()
            app_secret = str(
                item.get("app_secret")
                or item.get("appSecret")
                or item.get("clientSecret")
                or item.get("secret")
                or ""
            ).strip()
            bot_id = str(item.get("id") or item.get("binding_id") or uuid4().hex).strip()
            bots.append(
                {
                    "id": bot_id or uuid4().hex,
                    "enabled": bool(item.get("enabled", item.get("qq_bot_enabled", False))),
                    "remark": str(item.get("remark") or item.get("note") or "").strip(),
                    "app_id": app_id,
                    "app_secret": app_secret,
                }
            )

    config["im_integrations"]["qq"] = bots
    return config


def qq_bot_bindings(config: dict | None) -> list[dict]:
    normalized = normalize_workspace_config(config)
    return list((normalized.get("im_integrations") or {}).get("qq") or [])


def workspace_im_summary(config: dict | None) -> list[dict]:
    normalized = normalize_workspace_config(config)
    qq_bots = qq_bot_bindings(normalized)
    summary = []
    if qq_bots:
        enabled = sum(1 for bot in qq_bots if bot.get("enabled"))
        summary.append(
            {
                "type": "qq",
                "label": "QQ Bot",
                "count": len(qq_bots),
                "enabled_count": enabled,
            }
        )
    return summary


def workspace_has_im_bindings(config: dict | None) -> bool:
    return bool(workspace_im_summary(config))


def soul_file_path(project) -> Path:
    project_path = str(_project_snapshot(project).get("path") or "").strip()
    if not project_path:
        raise ValueError("项目路径不能为空")
    return Path(project_path).expanduser().resolve(strict=False) / SOUL_FILE_NAME


def workspace_soul_requested(value: dict | None) -> bool:
    if not isinstance(value, dict):
        return False
    if "soul_preset_id" in value or "soulPresetId" in value:
        return True
    soul = value.get("soul")
    return isinstance(soul, dict) and ("preset_id" in soul or "presetId" in soul)


def apply_workspace_soul(project, config: dict) -> None:
    preset_id = str((config or {}).get("soul_preset_id") or "").strip()
    if preset_id == MANUAL_SOUL_PRESET_ID:
        return

    path = soul_file_path(project)
    if not preset_id:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    preset = get_soul_preset(preset_id)
    if not preset:
        raise ValueError("SOUL 预设不存在")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(preset.get("content") or "").strip() + "\n", encoding="utf-8")


def _project_snapshot(project) -> dict:
    if hasattr(project, "model_dump"):
        return project.model_dump()
    return dict(project or {})
