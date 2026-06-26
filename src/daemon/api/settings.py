"""Settings API: providers, models, observability.

After any mutation the daemon's agent cache is reset so the next run rebuilds
agents with the new configuration (the checkpointer survives).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.user_data.config import (
    delete_soul_preset,
    get_assistant_config,
    get_observability_config,
    get_soul_presets,
    save_soul_preset,
    set_assistant_config,
    set_observability_config,
)
from core.user_data.projects import DEFAULT_PROJECT_ID, open_project
from core.user_data.workspace_config import (
    apply_workspace_soul,
    get_workspace_config,
    normalize_workspace_config,
    set_workspace_config,
    workspace_soul_requested,
)
from core.user_data.provider import (
    ModelConfig,
    ModelInfo,
    ProviderConfig,
    add_provider_config,
    cache_provider_models,
    fetch_available_models,
    remove_model_config,
    remove_provider_config,
    set_active_configured_model,
    set_models_for_provider,
    settings_snapshot,
    test_provider_connection,
    update_provider_config,
    upsert_model_config,
)
from daemon.api.protocol import fail, ok
from daemon.qq_bot import qq_bot_service
from daemon.runtime import reset_agents

router = APIRouter()


def _settings_with_observability() -> dict:
    settings = settings_snapshot()
    settings["observability"] = get_observability_config()
    settings["assistant"] = get_assistant_config()
    settings["assistantRuntime"] = qq_bot_service.status()
    settings["soulPresets"] = get_soul_presets()
    return settings


@router.post("/settings/get")
def get_settings():
    return ok(settings=_settings_with_observability())


# --- providers ---------------------------------------------------------

class ProviderBody(BaseModel):
    provider: dict
    originalName: str | None = None


@router.post("/settings/provider/save")
def save_provider(body: ProviderBody):
    original_name = (body.originalName or body.provider.get("original_name") or "").strip()
    config = ProviderConfig(
        type=body.provider.get("type") or "openai-compatible",
        name=(body.provider.get("name") or "").strip(),
        base_url=(body.provider.get("base_url") or "").strip(),
        api_key=body.provider.get("api_key") or "",
    )
    if original_name:
        update_provider_config(original_name, config)
    else:
        add_provider_config(config)
    reset_agents()
    return ok(settings=_settings_with_observability())


class ProviderNameBody(BaseModel):
    providerName: str


@router.post("/settings/provider/delete")
def delete_provider(body: ProviderNameBody):
    remove_provider_config(body.providerName)
    reset_agents()
    return ok(settings=_settings_with_observability())


@router.post("/settings/provider/test")
def test_provider(body: ProviderNameBody):
    result = test_provider_connection(body.providerName)
    result["settings"] = _settings_with_observability()
    return result


@router.post("/settings/provider/fetch-models")
def fetch_provider_models(body: ProviderNameBody):
    models = fetch_available_models(body.providerName)
    cache_provider_models(body.providerName, models)
    return ok(
        models=[model.model_dump() for model in models],
        settings=_settings_with_observability(),
    )


class EnableModelsBody(BaseModel):
    providerName: str
    modelNames: list[str]
    availableModels: list[dict] | None = None


@router.post("/settings/provider/enable-models")
def enable_provider_models(body: EnableModelsBody):
    model_infos = [
        ModelInfo(
            name=model.get("name") or "",
            context_length=int(model.get("context_length") or 0),
            max_tokens=int(model.get("max_tokens") or 0),
            support_data_types=model.get("support_data_types") or ["text"],
        )
        for model in (body.availableModels or [])
        if model.get("name")
    ]
    set_models_for_provider(body.providerName, body.modelNames, model_infos)
    reset_agents()
    return ok(settings=_settings_with_observability())


# --- models ------------------------------------------------------------

class ModelBody(BaseModel):
    model: dict


@router.post("/settings/model/save")
def save_model(body: ModelBody):
    m = body.model
    config = ModelConfig(
        provider_name=m.get("provider_name") or "",
        name=m.get("name") or "",
        display_name=m.get("display_name") or m.get("name") or "",
        enabled=bool(m.get("enabled", True)),
        temperature=float(m.get("temperature", 0)),
        max_tokens=int(m.get("max_tokens") or 0),
        context_length=int(m.get("context_length") or 0),
        support_data_types=m.get("support_data_types") or ["text"],
        input_price_per_million=float(m.get("input_price_per_million") or 0),
        cached_input_price_per_million=float(m.get("cached_input_price_per_million") or 0),
        output_price_per_million=float(m.get("output_price_per_million") or 0),
        currency=(m.get("currency") or "CNY").upper(),
    )
    upsert_model_config(config)
    if m.get("active"):
        set_active_configured_model(config.provider_name, config.name)
    reset_agents()
    return ok(settings=_settings_with_observability())


class DeleteModelBody(BaseModel):
    providerName: str
    modelName: str


@router.post("/settings/model/delete")
def delete_model(body: DeleteModelBody):
    remove_model_config(body.providerName, body.modelName)
    reset_agents()
    return ok(settings=_settings_with_observability())


class SetActiveModelBody(BaseModel):
    providerName: str
    modelName: str


@router.post("/settings/model/set-active")
def set_active_model(body: SetActiveModelBody):
    set_active_configured_model(body.providerName, body.modelName)
    reset_agents()
    return ok(settings=_settings_with_observability())


# --- observability -----------------------------------------------------

class ObservabilityBody(BaseModel):
    observability: dict


@router.post("/settings/observability/save")
def save_observability(body: ObservabilityBody):
    set_observability_config(body.observability or {})
    reset_agents()
    return ok(settings=_settings_with_observability())


# --- assistant ---------------------------------------------------------

class AssistantBody(BaseModel):
    assistant: dict


@router.post("/settings/assistant/save")
def save_assistant(body: AssistantBody):
    assistant = set_assistant_config(body.assistant or {})
    return ok(settings=_settings_with_observability())


# --- SOUL presets ------------------------------------------------------

class SoulPresetBody(BaseModel):
    soulPreset: dict
    originalId: str | None = None


class SoulPresetDeleteBody(BaseModel):
    presetId: str


@router.post("/settings/soul-preset/save")
def save_soul_preset_route(body: SoulPresetBody):
    try:
        preset = save_soul_preset(body.soulPreset or {}, body.originalId)
    except ValueError as exc:
        return fail(str(exc))
    reset_agents()
    return ok(settings=_settings_with_observability(), soulPreset=preset)


@router.post("/settings/soul-preset/delete")
def delete_soul_preset_route(body: SoulPresetDeleteBody):
    try:
        delete_soul_preset(body.presetId)
    except ValueError as exc:
        return fail(str(exc))
    reset_agents()
    return ok(settings=_settings_with_observability())


# --- workspace ---------------------------------------------------------

class WorkspaceSettingsBody(BaseModel):
    projectId: str = DEFAULT_PROJECT_ID
    workspaceConfig: dict | None = None


@router.post("/settings/workspace/get")
def get_workspace_settings(body: WorkspaceSettingsBody):
    project = open_project(body.projectId or DEFAULT_PROJECT_ID)
    config = get_workspace_config(project)
    return ok(
        workspaceConfig=config,
        workspaceRuntime=qq_bot_service.status_for_project(project, config),
    )


@router.post("/settings/workspace/save")
def save_workspace_settings(body: WorkspaceSettingsBody):
    project = open_project(body.projectId or DEFAULT_PROJECT_ID)
    raw_config = body.workspaceConfig or {}
    config = normalize_workspace_config(raw_config)
    if workspace_soul_requested(raw_config):
        try:
            apply_workspace_soul(project, config)
        except ValueError as exc:
            return fail(str(exc))
        reset_agents()
    config = set_workspace_config(project, config)
    qq_bot_service.configure_project(project, config)
    return ok(
        settings=_settings_with_observability(),
        workspaceConfig=config,
        workspaceRuntime=qq_bot_service.status_for_project(project, config),
    )
