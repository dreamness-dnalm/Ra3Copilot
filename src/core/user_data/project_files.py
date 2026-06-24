from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.user_data.projects import INVALID_PATH_CHARS, RESERVED_PATH_NAMES, ProjectEntry


MAX_TREE_ENTRIES = 900
MAX_TEXT_BYTES = 1_000_000
MAX_PREVIEW_BYTES = 2_000_000
HIDDEN_NAMES = {".ra3copilot-project.json"}
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".xml",
    ".ini",
    ".cfg",
    ".lua",
    ".cs",
    ".py",
    ".yml",
    ".yaml",
    ".mp",
    ".str",
    ".big",
}


def _project_root(project: ProjectEntry) -> Path:
    root = Path(project.path).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("路径不在当前工程内") from exc
    text = relative.as_posix()
    return "" if text == "." else text


def _resolve_project_path(project: ProjectEntry, relative_path: str | None = None) -> Path:
    root = _project_root(project)
    text = (relative_path or "").strip().replace("\\", "/")
    if not text:
        return root
    candidate = Path(text)
    if candidate.is_absolute() or ":" in candidate.drive:
        raise ValueError("只能访问当前工程内的相对路径")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("路径不能包含相对路径片段")
    path = (root / candidate).resolve(strict=False)
    _relative_path(path, root)
    return path


def _assert_valid_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("请输入名称")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError("名称不能包含路径分隔符")
    if INVALID_PATH_CHARS.search(cleaned):
        raise ValueError("名称包含不允许的特殊字符")
    if cleaned.rstrip(" .") != cleaned:
        raise ValueError("名称不能以空格或句点结尾")
    if cleaned.upper().split(".")[0] in RESERVED_PATH_NAMES:
        raise ValueError("名称使用了 Windows 保留名称")
    return cleaned


def _modified_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    except OSError:
        return ""


def _looks_editable(path: Path) -> bool:
    if path.is_dir():
        return False
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return True
    try:
        with path.open("rb") as file:
            chunk = file.read(4096)
    except OSError:
        return False
    return b"\x00" not in chunk


def _node_for(path: Path, root: Path, depth: int, counter: list[int]) -> dict:
    counter[0] += 1
    if counter[0] > MAX_TREE_ENTRIES:
        return {
            "name": "更多文件未加载",
            "path": "",
            "type": "notice",
            "children": [],
            "editable": False,
            "size": 0,
            "modifiedAt": "",
        }

    is_dir = path.is_dir()
    node = {
        "name": path.name,
        "path": _relative_path(path, root),
        "type": "folder" if is_dir else "file",
        "children": [],
        "editable": _looks_editable(path),
        "size": path.stat().st_size if path.is_file() else 0,
        "modifiedAt": _modified_iso(path),
    }

    if is_dir and depth > 0:
        try:
            children = [
                child
                for child in path.iterdir()
                if child.name not in HIDDEN_NAMES and not child.name.startswith(".__")
            ]
        except OSError:
            children = []
        children.sort(key=lambda child: (not child.is_dir(), child.name.lower()))
        node["children"] = [_node_for(child, root, depth - 1, counter) for child in children]
    return node


def list_project_files(project: ProjectEntry) -> dict:
    root = _project_root(project)
    counter = [0]
    try:
        children = [
            child
            for child in root.iterdir()
            if child.name not in HIDDEN_NAMES and not child.name.startswith(".__")
        ]
    except OSError:
        children = []
    children.sort(key=lambda child: (not child.is_dir(), child.name.lower()))
    return {
        "rootName": project.name,
        "items": [_node_for(child, root, 7, counter) for child in children],
        "entryCount": counter[0],
        "truncated": counter[0] >= MAX_TREE_ENTRIES,
    }


def _decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("文件不是可编辑文本")


def read_project_file(project: ProjectEntry, relative_path: str) -> dict:
    path = _resolve_project_path(project, relative_path)
    if not path.exists() or not path.is_file():
        raise ValueError("文件不存在")
    size = path.stat().st_size
    if size > MAX_PREVIEW_BYTES:
        raise ValueError("文件过大，暂不支持预览")
    data = path.read_bytes()
    if b"\x00" in data[:4096]:
        raise ValueError("二进制文件暂不支持预览")
    content, encoding = _decode_text(data)
    return {
        "name": path.name,
        "path": _relative_path(path, _project_root(project)),
        "content": content,
        "encoding": encoding,
        "editable": size <= MAX_TEXT_BYTES,
        "size": size,
        "modifiedAt": _modified_iso(path),
    }


def save_project_file(project: ProjectEntry, relative_path: str, content: str, encoding: str | None = None) -> dict:
    path = _resolve_project_path(project, relative_path)
    if not path.exists() or not path.is_file():
        raise ValueError("文件不存在")
    text = content or ""
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("文件内容过大，暂不支持保存")
    chosen_encoding = encoding if encoding in {"utf-8-sig", "utf-8", "utf-16", "gb18030"} else "utf-8"
    path.write_text(text, encoding=chosen_encoding)
    return read_project_file(project, relative_path)


def create_project_item(project: ProjectEntry, parent_path: str | None, name: str, kind: str = "file") -> dict:
    parent = _resolve_project_path(project, parent_path)
    if not parent.exists() or not parent.is_dir():
        raise ValueError("目标文件夹不存在")
    item_name = _assert_valid_name(name)
    target = (parent / item_name).resolve(strict=False)
    _relative_path(target, _project_root(project))
    if target.exists():
        raise ValueError("同名文件或文件夹已存在")
    if kind == "folder":
        target.mkdir(parents=False)
    else:
        target.write_text("", encoding="utf-8")
    return {"path": _relative_path(target, _project_root(project)), "tree": list_project_files(project)}


def rename_project_item(project: ProjectEntry, relative_path: str, new_name: str) -> dict:
    path = _resolve_project_path(project, relative_path)
    if not path.exists():
        raise ValueError("文件或文件夹不存在")
    item_name = _assert_valid_name(new_name)
    target = (path.parent / item_name).resolve(strict=False)
    _relative_path(target, _project_root(project))
    if target.exists():
        raise ValueError("同名文件或文件夹已存在")
    path.rename(target)
    return {"path": _relative_path(target, _project_root(project)), "tree": list_project_files(project)}


def delete_project_item(project: ProjectEntry, relative_path: str) -> dict:
    path = _resolve_project_path(project, relative_path)
    root = _project_root(project)
    if path == root:
        raise ValueError("不能删除工程根目录")
    if not path.exists():
        raise ValueError("文件或文件夹不存在")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return {"tree": list_project_files(project)}
