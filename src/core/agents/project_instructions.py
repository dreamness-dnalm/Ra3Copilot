from __future__ import annotations

from pathlib import Path

from core.agents.project_skills import resolve_project_root


PROJECT_INSTRUCTION_FILES = ("AGENTS.md", "SOUL.md", "USER.md")
MAX_INSTRUCTION_FILE_CHARS = 80_000
MAX_TOTAL_INSTRUCTION_CHARS = 180_000


def project_instruction_paths(project_path: str | Path | None) -> list[Path]:
    """Find supported instruction files directly under the project root."""
    root = resolve_project_root(project_path)
    paths: list[Path] = []
    for name in PROJECT_INSTRUCTION_FILES:
        path = root / name
        if path.is_file():
            paths.append(path)
    return paths


def _read_instruction(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if len(text) > MAX_INSTRUCTION_FILE_CHARS:
        return (
            text[:MAX_INSTRUCTION_FILE_CHARS]
            + "\n\n[Project instruction file truncated because it exceeded the per-file load limit.]"
        )
    return text


def load_project_instruction_files(project_path: str | Path | None) -> str:
    """Load AGENTS.md, SOUL.md and USER.md from the project root."""
    paths = project_instruction_paths(project_path)
    if not paths:
        return ""

    parts = [
        "## Project instruction files",
        "",
        "The following files were loaded automatically from the project root. "
        "Treat them as project-specific user instructions when they are relevant.",
    ]
    total_chars = 0

    for path in paths:
        text = _read_instruction(path)
        if not text:
            continue

        remaining = MAX_TOTAL_INSTRUCTION_CHARS - total_chars
        if remaining <= 0:
            parts.append("\n[More project instruction files were omitted because the total load limit was reached.]")
            break
        if len(text) > remaining:
            text = text[:remaining] + "\n\n[Project instruction files truncated because the total load limit was reached.]"

        parts.extend(["", f"--- project instruction: {path.name} ---", text])
        total_chars += len(text)

    if len(parts) <= 3:
        return ""
    return "\n".join(parts)
