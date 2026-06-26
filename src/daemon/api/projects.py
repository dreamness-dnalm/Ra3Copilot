"""Projects API.

Stateless: project selection lives in the client. Directory/file picking is
performed client-side (native dialog) and only the chosen path is sent here,
so this router never touches a window handle.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.user_data.history import list_conversations
from core.user_data.projects import (
    DEFAULT_PROJECT_ID,
    ProjectEntry,
    create_assistant_project_at,
    create_map_project_at,
    create_workspace_project_at,
    has_project_metadata,
    list_projects,
    open_assistant_project_from_directory,
    open_map_project_from_directory,
    open_map_project_from_file,
    open_project,
    open_workspace_project_from_directory,
    remove_recent_project,
)
from daemon.api.protocol import ok

router = APIRouter()


def _entry(project: ProjectEntry) -> dict:
    return project.model_dump()


def _full_snapshot(project: ProjectEntry | None = None, *, initialized: bool = False) -> dict:
    return {
        "ok": True,
        "projects": list_projects(project),
        "context": {"project": _entry(project) if project else None},
        "history": list_conversations(project) if project else [],
        "projectInit": {
            "initialized": bool(initialized),
            "projectId": project.id if project else "",
        },
    }


class OpenProjectBody(BaseModel):
    projectId: str = DEFAULT_PROJECT_ID


@router.post("/projects/list")
def list_all(body: OpenProjectBody | None = None):
    project_id = body.projectId if body else None
    current = open_project(project_id or DEFAULT_PROJECT_ID) if project_id else None
    return ok(projects=list_projects(current))


@router.post("/projects/open")
def open_existing(body: OpenProjectBody):
    project = open_project(body.projectId or DEFAULT_PROJECT_ID)
    return _full_snapshot(project)


class CreateProjectBody(BaseModel):
    name: str | None = None
    projectPath: str | None = None


@router.post("/projects/create-map")
def create_map(body: CreateProjectBody):
    project = create_map_project_at(name=body.name, project_path=body.projectPath)
    return _full_snapshot(project, initialized=True)


@router.post("/projects/create-workspace")
def create_workspace(body: CreateProjectBody):
    project = create_workspace_project_at(name=body.name, project_path=body.projectPath)
    return _full_snapshot(project, initialized=True)


@router.post("/projects/create-openclaw")
@router.post("/projects/create-assistant")
def create_assistant(body: CreateProjectBody):
    project = create_assistant_project_at(name=body.name, project_path=body.projectPath)
    return _full_snapshot(project, initialized=True)


class OpenFromPathBody(BaseModel):
    path: str


@router.post("/projects/open-map-from-path")
def open_map_from_path(body: OpenFromPathBody):
    """Open a map project from an already-picked directory or .mp file path."""
    from pathlib import Path

    resolved = Path(str(body.path)).expanduser().resolve(strict=False)
    project_dir = resolved if resolved.is_dir() else resolved.parent
    initialized = not has_project_metadata(project_dir)
    if resolved.is_dir():
        project = open_map_project_from_directory(str(resolved))
    else:
        project = open_map_project_from_file(str(resolved))
    return _full_snapshot(project, initialized=initialized)


@router.post("/projects/open-workspace-from-path")
def open_workspace_from_path(body: OpenFromPathBody):
    initialized = not has_project_metadata(body.path)
    project = open_workspace_project_from_directory(body.path)
    return _full_snapshot(project, initialized=initialized)


@router.post("/projects/open-openclaw-from-path")
@router.post("/projects/open-assistant-from-path")
def open_assistant_from_path(body: OpenFromPathBody):
    initialized = not has_project_metadata(body.path)
    project = open_assistant_project_from_directory(body.path)
    return _full_snapshot(project, initialized=initialized)


class RemoveProjectBody(BaseModel):
    projectId: str
    currentProject: dict | None = None


@router.post("/projects/remove-recent")
def remove_recent(body: RemoveProjectBody):
    remove_recent_project(body.projectId)
    current = ProjectEntry(**body.currentProject) if body.currentProject else None
    return _full_snapshot(current)
