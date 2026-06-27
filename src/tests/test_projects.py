from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import warnings
from pathlib import Path

_APPDATA_DIR = tempfile.TemporaryDirectory(prefix="ra3copilot-projects-appdata-")
os.environ["APPDATA"] = _APPDATA_DIR.name

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from core.user_data import projects


class ProjectKindTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data_root = Path(_APPDATA_DIR.name) / "Ra3Copilot"
        shutil.rmtree(self.data_root, ignore_errors=True)
        projects.PROJECTS_DIR = self.data_root / "projects"
        projects.PROJECT_INDEX_PATH = self.data_root / "projects.json"

    def test_legacy_assistant_project_routes_create_workspace_project(self) -> None:
        target = self.data_root / "custom-assistant"

        entry = projects.create_assistant_project_at("Assistant Notes", str(target))

        self.assertEqual(entry.kind, "workspace")
        self.assertEqual(Path(entry.path), target)
        self.assertTrue((target / "project.co").exists())
        self.assertFalse((target / ".ra3copilot-project.json").exists())
        self.assertTrue((target / "AGENTS.md").exists())
        with (target / "project.co").open("r", encoding="utf-8") as file:
            self.assertEqual(json.load(file)["kind"], "workspace")

        snapshot = projects.list_projects(entry)
        recent = snapshot["recentProjects"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["kind"], "workspace")
        self.assertNotIn("assistant", snapshot["projectRoots"])

    def test_default_project_roots_are_separate_by_kind(self) -> None:
        map_project = projects.create_map_project_at("Map Project")
        workspace = projects.create_workspace_project_at("General Workspace")
        assistant = projects.create_assistant_project_at("Helpful Assistant")

        self.assertEqual(Path(map_project.path).parent, self.data_root / "projects" / "maps")
        self.assertEqual(Path(workspace.path).parent, self.data_root / "projects" / "workspaces")
        self.assertEqual(Path(assistant.path).parent, self.data_root / "projects" / "workspaces")

    def test_opening_directory_initializes_project_files_without_overwriting_agents(self) -> None:
        shared = self.data_root / "opened-workspace"
        shared.mkdir(parents=True)
        agents_path = shared / "AGENTS.md"
        agents_path.write_text("Custom agent rules", encoding="utf-8")

        workspace = projects.open_workspace_project_from_directory(str(shared))

        self.assertEqual(workspace.kind, "workspace")
        self.assertTrue((shared / "project.co").exists())
        self.assertEqual(agents_path.read_text(encoding="utf-8"), "Custom agent rules")

    def test_opening_directory_without_agents_creates_default_agents_file(self) -> None:
        shared = self.data_root / "fresh-opened-workspace"
        shared.mkdir(parents=True)

        workspace = projects.open_workspace_project_from_directory(str(shared))

        self.assertEqual(workspace.kind, "workspace")
        self.assertTrue((shared / "project.co").exists())
        self.assertTrue((shared / "AGENTS.md").exists())

    def test_explicit_opening_recategorizes_existing_directory(self) -> None:
        shared = self.data_root / "shared"
        shared.mkdir(parents=True)

        workspace = projects.open_workspace_project_from_directory(str(shared))
        self.assertEqual(workspace.kind, "workspace")

        assistant = projects.open_assistant_project_from_directory(str(shared))
        self.assertEqual(assistant.id, workspace.id)
        self.assertEqual(assistant.kind, "workspace")

        map_project = projects.open_map_project_from_directory(str(shared))
        self.assertEqual(map_project.id, workspace.id)
        self.assertEqual(map_project.kind, "map")
        self.assertTrue(any(path.suffix.lower() == ".mp" for path in shared.iterdir()))

    def test_legacy_assistant_project_api_route_creates_workspace(self) -> None:
        from fastapi.testclient import TestClient

        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        target = self.data_root / "api-assistant"
        client = TestClient(create_app(), client=("127.0.0.1", 50100))
        response = client.post(
            "/projects/create-assistant",
            json={"name": "API Assistant", "projectPath": str(target)},
            headers={"X-Ra3Copilot-Token": get_or_create_token()},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body.get("ok"), True)
        self.assertEqual(body["context"]["project"]["kind"], "workspace")
        self.assertEqual(body["projects"]["currentProject"]["kind"], "workspace")
        self.assertTrue(body["projectInit"]["initialized"])

    def test_legacy_openclaw_api_route_creates_workspace(self) -> None:
        from fastapi.testclient import TestClient

        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        target = self.data_root / "api-openclaw-legacy"
        client = TestClient(create_app(), client=("127.0.0.1", 50101))
        response = client.post(
            "/projects/create-openclaw",
            json={"name": "Legacy Claw", "projectPath": str(target)},
            headers={"X-Ra3Copilot-Token": get_or_create_token()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["context"]["project"]["kind"], "workspace")

    def test_open_existing_directory_reports_initialized_only_once(self) -> None:
        from fastapi.testclient import TestClient

        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        target = self.data_root / "api-open-workspace"
        target.mkdir(parents=True)
        client = TestClient(create_app(), client=("127.0.0.1", 50102))
        headers = {"X-Ra3Copilot-Token": get_or_create_token()}

        first = client.post(
            "/projects/open-workspace-from-path",
            json={"path": str(target)},
            headers=headers,
        )
        second = client.post(
            "/projects/open-workspace-from-path",
            json={"path": str(target)},
            headers=headers,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.json()["projectInit"]["initialized"])
        self.assertFalse(second.json()["projectInit"]["initialized"])


if __name__ == "__main__":
    unittest.main()
