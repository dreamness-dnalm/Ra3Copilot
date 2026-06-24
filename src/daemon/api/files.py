"""Project files API: tree / read / save / create / rename / delete.

All operations are sandboxed to the project root by ``project_files.py``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from core.user_data.project_files import (
    create_project_item,
    delete_project_item,
    list_project_files,
    read_project_file,
    rename_project_item,
    save_project_file,
)
from core.user_data.projects import DEFAULT_PROJECT_ID, ProjectEntry, open_project
from daemon.api.protocol import ok

router = APIRouter()


def _resolve(project_body: dict | None, project_id: str | None) -> ProjectEntry:
    if project_body:
        return ProjectEntry(**project_body)
    return open_project(project_id or DEFAULT_PROJECT_ID)


class ProjectRefBody(BaseModel):
    project: dict | None = None
    projectId: str | None = None


@router.post("/files/tree")
def get_tree(body: ProjectRefBody):
    project = _resolve(body.project, body.projectId)
    return ok(tree=list_project_files(project))


class ReadFileBody(ProjectRefBody):
    path: str


@router.post("/files/read")
def read_file(body: ReadFileBody):
    project = _resolve(body.project, body.projectId)
    return ok(file=read_project_file(project, body.path))


class SaveFileBody(ProjectRefBody):
    path: str
    content: str
    encoding: str | None = None


@router.post("/files/save")
def save_file(body: SaveFileBody):
    project = _resolve(body.project, body.projectId)
    file_snapshot = save_project_file(project, body.path, body.content, body.encoding)
    return ok(file=file_snapshot, tree=list_project_files(project))


class CreateItemBody(ProjectRefBody):
    parentPath: str | None = None
    name: str
    kind: str = "file"


@router.post("/files/create")
def create_item(body: CreateItemBody):
    project = _resolve(body.project, body.projectId)
    result = create_project_item(project, body.parentPath, body.name, body.kind)
    return ok(**result)


class RenameItemBody(ProjectRefBody):
    path: str
    newName: str


@router.post("/files/rename")
def rename_item(body: RenameItemBody):
    project = _resolve(body.project, body.projectId)
    result = rename_project_item(project, body.path, body.newName)
    return ok(**result)


class DeleteItemBody(ProjectRefBody):
    path: str


@router.post("/files/delete")
def delete_item(body: DeleteItemBody):
    project = _resolve(body.project, body.projectId)
    result = delete_project_item(project, body.path)
    return ok(**result)
