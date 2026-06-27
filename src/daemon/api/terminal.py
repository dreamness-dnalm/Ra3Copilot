"""Workspace terminal API.

This is intentionally a command runner rather than a long-lived PTY. Each
request executes one shell command in the project root and returns captured
stdout/stderr so the desktop UI can host lightweight terminal tabs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from core.user_data.projects import DEFAULT_PROJECT_ID, ProjectEntry, open_project
from daemon.api.protocol import fail, ok

router = APIRouter()

MAX_COMMAND_CHARS = 8_000
MAX_OUTPUT_CHARS = 200_000
MAX_TIMEOUT_SECONDS = 120
DEFAULT_TIMEOUT_SECONDS = 30


def _resolve(project_body: dict | None, project_id: str | None) -> ProjectEntry:
    if project_body:
        return ProjectEntry(**project_body)
    return open_project(project_id or DEFAULT_PROJECT_ID)


def _clip_output(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + "\n...[output truncated]", True


def _shell_command(command: str) -> list[str]:
    if sys.platform.startswith("win"):
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ]
    shell = os.environ.get("SHELL") or "/bin/sh"
    return [shell, "-lc", command]


class TerminalRunBody(BaseModel):
    project: dict | None = None
    projectId: str | None = None
    command: str
    timeoutSeconds: int | None = DEFAULT_TIMEOUT_SECONDS


@router.post("/terminal/run")
def run_terminal_command(body: TerminalRunBody):
    command = str(body.command or "").strip()
    if not command:
        return fail("命令不能为空")
    if len(command) > MAX_COMMAND_CHARS:
        return fail("命令过长")

    project = _resolve(body.project, body.projectId)
    cwd = Path(project.path).expanduser().resolve(strict=False)
    cwd.mkdir(parents=True, exist_ok=True)
    timeout = max(1, min(int(body.timeoutSeconds or DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS))

    try:
        completed = subprocess.run(
            _shell_command(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        stdout, stdout_truncated = _clip_output(completed.stdout or "")
        stderr, stderr_truncated = _clip_output(completed.stderr or "")
        return ok(
            command=command,
            cwd=str(cwd),
            exitCode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            timedOut=False,
            truncated=stdout_truncated or stderr_truncated,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
        stdout, stdout_truncated = _clip_output(stdout or "")
        stderr, stderr_truncated = _clip_output(stderr or "")
        return ok(
            command=command,
            cwd=str(cwd),
            exitCode=None,
            stdout=stdout,
            stderr=stderr,
            timedOut=True,
            truncated=stdout_truncated or stderr_truncated,
        )
    except OSError as exc:
        return fail(str(exc))
