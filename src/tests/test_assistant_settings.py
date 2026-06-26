from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

_APPDATA_DIR = tempfile.TemporaryDirectory(prefix="ra3copilot-assistant-settings-")
os.environ["APPDATA"] = _APPDATA_DIR.name

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)


class WorkspaceImSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        from core.user_data import config, projects

        self.data_root = Path(_APPDATA_DIR.name) / "Ra3Copilot"
        shutil.rmtree(self.data_root, ignore_errors=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        config.config_file_path = str(self.data_root / "config.json")
        config.config_dict.clear()
        projects.PROJECTS_DIR = self.data_root / "projects"
        projects.PROJECT_INDEX_PATH = self.data_root / "projects.json"

    def test_workspace_settings_api_persists_multiple_im_bindings(self) -> None:
        from fastapi.testclient import TestClient

        from core.user_data import projects
        from core.user_data.workspace_config import workspace_config_path
        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        project = projects.create_workspace_project_at(
            "Workspace One",
            str(self.data_root / "workspace-one"),
        )
        other_project = projects.create_map_project_at(
            "Map Two",
            str(self.data_root / "map-two"),
        )
        payload = {
            "soul_preset_id": "",
            "im_integrations": {
                "qq": [
                    {
                        "id": "personal",
                        "enabled": True,
                        "remark": "个人单聊",
                        "app_id": "102012345",
                        "app_secret": "app-secret-value",
                    },
                    {
                        "id": "group",
                        "enabled": False,
                        "remark": "项目群",
                        "app_id": "102067890",
                        "app_secret": "another-secret",
                    },
                ]
            },
        }

        client = TestClient(create_app(), client=("127.0.0.1", 50200))
        token = get_or_create_token()
        with patch("daemon.api.settings.qq_bot_service.configure_project") as configure_project:
            saved = client.post(
                "/settings/workspace/save",
                json={"projectId": project.id, "workspaceConfig": payload},
                headers={"X-Ra3Copilot-Token": token},
            )

        self.assertEqual(saved.status_code, 200)
        saved_body = saved.json()
        self.assertEqual(saved_body["workspaceConfig"], payload)
        configure_project.assert_called_once()
        configured_project, configured_payload = configure_project.call_args.args
        self.assertEqual(configured_project.id, project.id)
        self.assertEqual(configured_payload, payload)

        config_path = workspace_config_path(project)
        self.assertEqual(config_path, Path(project.path) / ".agent" / "workspace_config.json")
        with config_path.open("r", encoding="utf-8") as file:
            self.assertEqual(json.load(file), payload)

        loaded = client.post(
            "/settings/workspace/get",
            json={"projectId": project.id},
            headers={"X-Ra3Copilot-Token": token},
        )
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["workspaceConfig"], payload)

        other_loaded = client.post(
            "/settings/workspace/get",
            json={"projectId": other_project.id},
            headers={"X-Ra3Copilot-Token": token},
        )
        self.assertEqual(other_loaded.status_code, 200)
        self.assertEqual(
            other_loaded.json()["workspaceConfig"],
            {"im_integrations": {"qq": []}, "soul_preset_id": ""},
        )

    def test_project_list_reports_all_im_bound_projects(self) -> None:
        from fastapi.testclient import TestClient

        from core.user_data import projects
        from core.user_data.workspace_config import set_workspace_config
        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        workspace = projects.create_workspace_project_at(
            "Workspace With IM",
            str(self.data_root / "workspace-with-im"),
        )
        map_project = projects.create_map_project_at(
            "Map With IM",
            str(self.data_root / "map-with-im"),
        )
        plain = projects.create_workspace_project_at(
            "Plain Workspace",
            str(self.data_root / "plain-workspace"),
        )
        set_workspace_config(
            workspace,
            {"im_integrations": {"qq": [{"id": "qq-1", "enabled": True, "app_id": "1", "app_secret": "s"}]}},
        )
        set_workspace_config(
            map_project,
            {"qq_bots": [{"id": "legacy", "enabled": False, "app_id": "", "app_secret": ""}]},
        )

        client = TestClient(create_app(), client=("127.0.0.1", 50201))
        response = client.post(
            "/projects/list",
            json={},
            headers={"X-Ra3Copilot-Token": get_or_create_token()},
        )

        self.assertEqual(response.status_code, 200)
        bound = response.json()["projects"]["imBoundProjects"]
        names = {project["name"] for project in bound}
        self.assertIn(workspace.name, names)
        self.assertIn(map_project.name, names)
        self.assertNotIn(plain.name, names)
        summary_by_name = {project["name"]: project["imIntegrations"] for project in bound}
        self.assertEqual(summary_by_name[workspace.name][0]["type"], "qq")


if __name__ == "__main__":
    unittest.main()
