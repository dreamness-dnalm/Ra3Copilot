from __future__ import annotations

import hashlib
from pathlib import Path


PROJECT_SKILLS_DIR = Path(".agent") / "skills"
SKILL_FILE_NAME = "SKILL.md"
MAX_SKILL_CHARS = 120_000
MAX_TOTAL_SKILL_CHARS = 360_000


def resolve_project_root(project_path: str | Path | None) -> Path:
    """Return a stable project root for agent backends and project skills."""
    if project_path:
        return Path(project_path).expanduser().resolve(strict=False)
    return Path.cwd().resolve(strict=False)


def _skill_root(project_path: str | Path | None) -> Path:
    return resolve_project_root(project_path) / PROJECT_SKILLS_DIR


def _relative_label(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.name


def project_skill_paths(project_path: str | Path | None) -> list[Path]:
    """Find project-local skill entrypoints under .agent/skills."""
    root = _skill_root(project_path)
    if not root.is_dir():
        return []

    try:
        paths = [path for path in root.rglob(SKILL_FILE_NAME) if path.is_file()]
    except OSError:
        return []

    project_root = resolve_project_root(project_path)
    return sorted(paths, key=lambda path: _relative_label(path, project_root).casefold())


def project_skills_signature(project_path: str | Path | None) -> str:
    """Return a compact cache key component for project-local skills."""
    project_root = resolve_project_root(project_path)
    parts: list[str] = []
    for path in project_skill_paths(project_root):
        try:
            stat = path.stat()
        except OSError:
            continue
        label = _relative_label(path, project_root)
        parts.append(f"{label}\0{stat.st_size}\0{stat.st_mtime_ns}")

    if not parts:
        return "none"

    payload = "\n".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()[:16]


def _read_skill(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if len(text) > MAX_SKILL_CHARS:
        return (
            text[:MAX_SKILL_CHARS]
            + "\n\n[Project skill truncated because it exceeded the per-file load limit.]"
        )
    return text


def load_project_skills(project_path: str | Path | None) -> str:
    """Load .agent/skills/**/SKILL.md files into a system prompt section."""
    project_root = resolve_project_root(project_path)
    paths = project_skill_paths(project_root)
    if not paths:
        return ""

    parts = [
        "## Project .agent/skills",
        "",
        "The following project-local skills were loaded automatically from "
        "`.agent/skills/**/SKILL.md`. Treat them as project-specific user "
        "instructions when they are relevant. If a skill references extra "
        "project files, inspect those files with the available filesystem "
        "tools before relying on them.",
    ]
    total_chars = 0

    for path in paths:
        text = _read_skill(path)
        if not text:
            continue

        remaining = MAX_TOTAL_SKILL_CHARS - total_chars
        if remaining <= 0:
            parts.append("\n[More project skills were omitted because the total load limit was reached.]")
            break
        if len(text) > remaining:
            text = text[:remaining] + "\n\n[Project skills truncated because the total load limit was reached.]"

        label = _relative_label(path, project_root)
        parts.extend(["", f"--- project skill: {label} ---", text])
        total_chars += len(text)

    if len(parts) <= 3:
        return ""
    return "\n".join(parts)
