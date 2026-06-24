from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.user_data import user_data_path


PROJECTS_DIR = Path(user_data_path) / "projects"
PROJECT_INDEX_PATH = Path(user_data_path) / "projects.json"
DEFAULT_PROJECT_ID = "default"
INVALID_PATH_CHARS = re.compile(r'[\x00-\x1f<>"|?*]')
RESERVED_PATH_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{idx}" for idx in range(1, 10)),
    *(f"LPT{idx}" for idx in range(1, 10)),
}


@dataclass(frozen=True)
class ProjectEntry:
    id: str
    name: str
    path: str
    kind: str
    created_at: str
    last_opened_at: str
    hidden: bool = False

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "kind": self.kind,
            "created_at": self.created_at,
            "last_opened_at": self.last_opened_at,
            "hidden": self.hidden,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_index() -> dict:
    if not PROJECT_INDEX_PATH.exists():
        return {"projects": [], "current_project_id": None}
    with PROJECT_INDEX_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        return {"projects": [], "current_project_id": None}
    data.setdefault("projects", [])
    data.setdefault("current_project_id", None)
    return data


def _save_index(index: dict) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROJECT_INDEX_PATH.open("w", encoding="utf-8") as file:
        json.dump(index, file, ensure_ascii=False, indent=2)


def _project_metadata_path(project_path: Path) -> Path:
    return project_path / ".ra3copilot-project.json"


def _write_project_metadata(entry: ProjectEntry) -> None:
    project_path = Path(entry.path)
    project_path.mkdir(parents=True, exist_ok=True)
    with _project_metadata_path(project_path).open("w", encoding="utf-8") as file:
        json.dump(entry.model_dump(), file, ensure_ascii=False, indent=2)


def _project_from_dict(value: dict) -> ProjectEntry:
    return ProjectEntry(
        id=str(value.get("id") or ""),
        name=str(value.get("name") or ""),
        path=str(value.get("path") or ""),
        kind=str(value.get("kind") or "map"),
        created_at=str(value.get("created_at") or ""),
        last_opened_at=str(value.get("last_opened_at") or ""),
        hidden=bool(value.get("hidden", False)),
    )


def _entry_index(index: dict, project_id: str) -> int:
    for idx, project in enumerate(index.get("projects", [])):
        if project.get("id") == project_id:
            return idx
    return -1


def _ensure_default_project(index: dict) -> ProjectEntry:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    idx = _entry_index(index, DEFAULT_PROJECT_ID)
    if idx >= 0:
        entry = _project_from_dict(index["projects"][idx])
    else:
        now = _now_iso()
        entry = ProjectEntry(
            id=DEFAULT_PROJECT_ID,
            name="默认工程",
            path=str(PROJECTS_DIR / DEFAULT_PROJECT_ID),
            kind="default",
            created_at=now,
            last_opened_at="",
            hidden=False,
        )
        index.setdefault("projects", []).insert(0, entry.model_dump())

    _write_project_metadata(entry)
    return entry


def _normalize_project_name(name: str | None) -> str:
    cleaned = (name or "").strip()
    return cleaned or f"地图工程 {datetime.now().strftime('%Y-%m-%d %H-%M')}"


def _safe_project_id(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name.strip())
    value = re.sub(r"\s+", "-", value).strip(".- ")
    if not value:
        value = f"map-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    return value[:80]


def _assert_valid_path_text(raw_path: str | None) -> Path:
    path_text = (raw_path or "").strip().strip('"')
    if not path_text:
        raise ValueError("请选择工程保存目录")
    if INVALID_PATH_CHARS.search(path_text):
        raise ValueError("保存目录包含不允许的特殊字符")

    colon_count = path_text.count(":")
    if colon_count > 1 or (colon_count == 1 and not re.match(r"^[A-Za-z]:($|[\\/])", path_text)):
        raise ValueError("保存目录包含不允许的特殊字符")

    segment_text = re.sub(r"^[A-Za-z]:[\\/]*", "", path_text)
    for segment in re.split(r"[\\/]+", segment_text):
        if not segment:
            continue
        if segment in {".", ".."}:
            raise ValueError("保存目录不能包含相对路径片段")
        cleaned = segment.rstrip(" .")
        if cleaned != segment:
            raise ValueError("保存目录的文件夹名称不能以空格或句点结尾")
        if cleaned.upper().split(".")[0] in RESERVED_PATH_NAMES:
            raise ValueError("保存目录使用了 Windows 保留名称")

    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = PROJECTS_DIR / path
    return path.resolve(strict=False)


def _entry_index_by_path(index: dict, project_path: Path) -> int:
    normalized = str(project_path.resolve(strict=False)).casefold()
    for idx, project in enumerate(index.get("projects", [])):
        current = Path(str(project.get("path") or "")).resolve(strict=False)
        if str(current).casefold() == normalized:
            return idx
    return -1


def _unique_project_id(index: dict, base: str) -> str:
    existing = {project.get("id") for project in index.get("projects", [])}
    project_id = base
    suffix = 2
    while project_id in existing or (PROJECTS_DIR / project_id).exists():
        project_id = f"{base}-{suffix}"
        suffix += 1
    return project_id


def _assert_new_project_directory(project_path: Path) -> None:
    if project_path.exists():
        if not project_path.is_dir():
            raise ValueError("工程保存目录必须是文件夹")
        if any(project_path.iterdir()):
            raise ValueError("新工程不能保存到非空文件夹")


def list_projects(current_project: ProjectEntry | None = None) -> dict:
    index = _load_index()
    default_project = _ensure_default_project(index)
    _save_index(index)

    projects = [_project_from_dict(project) for project in index.get("projects", [])]
    recent_projects = [
        project
        for project in projects
        if project.id != DEFAULT_PROJECT_ID and not project.hidden and project.last_opened_at
    ]
    recent_projects.sort(key=lambda project: project.last_opened_at, reverse=True)

    current = current_project
    if current is None:
        current_id = index.get("current_project_id")
        current = next((project for project in projects if project.id == current_id), None)

    return {
        "projectsDir": str(PROJECTS_DIR),
        "defaultProject": default_project.model_dump(),
        "currentProject": current.model_dump() if current else None,
        "recentProjects": [project.model_dump() for project in recent_projects],
    }


def open_project(project_id: str = DEFAULT_PROJECT_ID) -> ProjectEntry:
    index = _load_index()
    default_project = _ensure_default_project(index)
    target_id = project_id or DEFAULT_PROJECT_ID

    if target_id == DEFAULT_PROJECT_ID:
        entry = default_project
        idx = _entry_index(index, DEFAULT_PROJECT_ID)
    else:
        idx = _entry_index(index, target_id)
        if idx < 0:
            raise ValueError(f"工程不存在：{target_id}")
        entry = _project_from_dict(index["projects"][idx])

    entry = ProjectEntry(
        id=entry.id,
        name=entry.name,
        path=entry.path,
        kind=entry.kind,
        created_at=entry.created_at or _now_iso(),
        last_opened_at=_now_iso(),
        hidden=False,
    )

    index["projects"][idx] = entry.model_dump()
    index["current_project_id"] = entry.id
    _write_project_metadata(entry)
    _save_index(index)
    return entry


def create_map_project(name: str | None = None) -> ProjectEntry:
    return create_map_project_at(name=name, project_path=None)


def create_map_project_at(name: str | None = None, project_path: str | None = None) -> ProjectEntry:
    index = _load_index()
    _ensure_default_project(index)
    project_name = _normalize_project_name(name)
    if project_path:
        target_path = _assert_valid_path_text(project_path)
        if _entry_index_by_path(index, target_path) >= 0:
            raise ValueError("该目录已经在工程列表中")
        _assert_new_project_directory(target_path)
    else:
        project_id_for_path = _unique_project_id(index, _safe_project_id(project_name))
        target_path = PROJECTS_DIR / project_id_for_path
        _assert_new_project_directory(target_path)

    project_id = _unique_project_id(index, _safe_project_id(project_name))
    now = _now_iso()
    entry = ProjectEntry(
        id=project_id,
        name=project_name,
        path=str(target_path),
        kind="map",
        created_at=now,
        last_opened_at=now,
        hidden=False,
    )
    index.setdefault("projects", []).append(entry.model_dump())
    index["current_project_id"] = entry.id
    _write_project_metadata(entry)
    _save_index(index)
    return entry


def open_map_project_from_file(map_file_path: str) -> ProjectEntry:
    map_file = Path(map_file_path).expanduser().resolve(strict=False)
    if map_file.suffix.lower() != ".mp":
        raise ValueError("请选择 .mp 地图文件")
    if not map_file.exists() or not map_file.is_file():
        raise ValueError("选择的 .mp 文件不存在")

    project_path = map_file.parent.resolve(strict=False)
    index = _load_index()
    _ensure_default_project(index)
    idx = _entry_index_by_path(index, project_path)
    now = _now_iso()
    if idx >= 0:
        current = _project_from_dict(index["projects"][idx])
        entry = ProjectEntry(
            id=current.id,
            name=current.name or project_path.name or map_file.stem,
            path=str(project_path),
            kind=current.kind or "map",
            created_at=current.created_at or now,
            last_opened_at=now,
            hidden=False,
        )
        index["projects"][idx] = entry.model_dump()
    else:
        project_name = project_path.name or map_file.stem or "地图工程"
        project_id = _unique_project_id(index, _safe_project_id(project_name) or f"map-{uuid4().hex[:8]}")
        entry = ProjectEntry(
            id=project_id,
            name=project_name,
            path=str(project_path),
            kind="map",
            created_at=now,
            last_opened_at=now,
            hidden=False,
        )
        index.setdefault("projects", []).append(entry.model_dump())

    index["current_project_id"] = entry.id
    _write_project_metadata(entry)
    _save_index(index)
    return entry


def open_map_project_from_directory(project_directory: str) -> ProjectEntry:
    project_path = Path(project_directory).expanduser().resolve(strict=False)
    if not project_path.exists() or not project_path.is_dir():
        raise ValueError("请选择地图工程文件夹")

    map_files = sorted(
        (path for path in project_path.iterdir() if path.is_file() and path.suffix.lower() == ".mp"),
        key=lambda path: path.name.lower(),
    )
    if map_files:
        return open_map_project_from_file(str(map_files[0]))

    map_stem = _safe_project_id(project_path.name or "map")
    if not map_stem:
        map_stem = "map"
    map_file = project_path / f"{map_stem}.mp"
    suffix = 2
    while map_file.exists():
        map_file = project_path / f"{map_stem}-{suffix}.mp"
        suffix += 1
    map_file.touch()
    return open_map_project_from_file(str(map_file))


def remove_recent_project(project_id: str) -> None:
    if project_id == DEFAULT_PROJECT_ID:
        return
    index = _load_index()
    idx = _entry_index(index, project_id)
    if idx < 0:
        return
    project = dict(index["projects"][idx])
    project["hidden"] = True
    index["projects"][idx] = project
    _save_index(index)
