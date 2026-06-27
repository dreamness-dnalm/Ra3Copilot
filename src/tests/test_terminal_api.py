from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

_APPDATA_DIR = tempfile.TemporaryDirectory(prefix="ra3copilot-terminal-appdata-")
os.environ["APPDATA"] = _APPDATA_DIR.name

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)


class TerminalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from core.user_data import projects

        self.data_root = Path(_APPDATA_DIR.name) / "Ra3Copilot"
        shutil.rmtree(self.data_root, ignore_errors=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        projects.PROJECTS_DIR = self.data_root / "projects"
        projects.PROJECT_INDEX_PATH = self.data_root / "projects.json"

    def test_terminal_command_runs_in_project_directory(self) -> None:
        from fastapi.testclient import TestClient

        from core.user_data import projects
        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        project = projects.create_workspace_project_at(
            "Terminal Workspace",
            str(self.data_root / "terminal-workspace"),
        )
        python_cmd = (
            f'& "{sys.executable}" -c "import pathlib; print(pathlib.Path.cwd().name)"'
            if sys.platform.startswith("win")
            else f'"{sys.executable}" -c "import pathlib; print(pathlib.Path.cwd().name)"'
        )
        client = TestClient(create_app(), client=("127.0.0.1", 50106))
        response = client.post(
            "/terminal/run",
            json={
                "project": project.model_dump(),
                "command": python_cmd,
            },
            headers={"X-Ra3Copilot-Token": get_or_create_token()},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body.get("ok"), True)
        self.assertEqual(body.get("exitCode"), 0)
        self.assertIn("terminal-workspace", body.get("stdout", ""))

    def test_terminal_command_rejects_empty_command(self) -> None:
        from fastapi.testclient import TestClient

        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        client = TestClient(create_app(), client=("127.0.0.1", 50107))
        response = client.post(
            "/terminal/run",
            json={"command": "   "},
            headers={"X-Ra3Copilot-Token": get_or_create_token()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json().get("ok"), False)


if __name__ == "__main__":
    unittest.main()
