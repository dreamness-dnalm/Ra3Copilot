from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import warnings
from pathlib import Path

_APPDATA_DIR = tempfile.TemporaryDirectory(prefix="ra3copilot-soul-settings-")
os.environ["APPDATA"] = _APPDATA_DIR.name

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)


class SoulSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        from core.user_data import config, projects

        self.data_root = Path(_APPDATA_DIR.name) / "Ra3Copilot"
        shutil.rmtree(self.data_root, ignore_errors=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        config.config_file_path = str(self.data_root / "config.json")
        config.config_dict.clear()
        projects.PROJECTS_DIR = self.data_root / "projects"
        projects.PROJECT_INDEX_PATH = self.data_root / "projects.json"

    def test_settings_api_manages_custom_soul_presets(self) -> None:
        from fastapi.testclient import TestClient

        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        client = TestClient(create_app(), client=("127.0.0.1", 50300))
        headers = {"X-Ra3Copilot-Token": get_or_create_token()}

        loaded = client.post("/settings/get", json={}, headers=headers)
        self.assertEqual(loaded.status_code, 200)
        builtins = loaded.json()["settings"]["soulPresets"]
        self.assertEqual(
            [preset["name"] for preset in builtins[:3]],
            ["RA3游戏专家", "可靠助理", "萌萌猫娘"],
        )
        self.assertTrue(all(preset["builtin"] for preset in builtins[:3]))

        created = client.post(
            "/settings/soul-preset/save",
            json={"soulPreset": {"name": "自定义助理", "content": "Be precise."}},
            headers=headers,
        )
        self.assertEqual(created.status_code, 200)
        created_body = created.json()
        self.assertTrue(created_body["ok"])
        custom_id = created_body["soulPreset"]["id"]
        self.assertFalse(created_body["soulPreset"]["builtin"])

        updated = client.post(
            "/settings/soul-preset/save",
            json={
                "originalId": custom_id,
                "soulPreset": {"id": custom_id, "name": "自定义助理 2", "content": "Be reliable."},
            },
            headers=headers,
        )
        self.assertTrue(updated.json()["ok"])
        self.assertEqual(updated.json()["soulPreset"]["id"], custom_id)
        self.assertIn("Be reliable.", updated.json()["soulPreset"]["content"])

        rejected = client.post(
            "/settings/soul-preset/delete",
            json={"presetId": "builtin-ra3-game-expert"},
            headers=headers,
        )
        self.assertFalse(rejected.json()["ok"])

        deleted = client.post(
            "/settings/soul-preset/delete",
            json={"presetId": custom_id},
            headers=headers,
        )
        self.assertTrue(deleted.json()["ok"])
        ids = [preset["id"] for preset in deleted.json()["settings"]["soulPresets"]]
        self.assertNotIn(custom_id, ids)

    def test_workspace_soul_preset_writes_soul_md(self) -> None:
        from fastapi.testclient import TestClient

        from core.user_data import projects
        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        project = projects.create_workspace_project_at(
            "Soul Workspace",
            str(self.data_root / "soul-workspace"),
        )
        client = TestClient(create_app(), client=("127.0.0.1", 50301))
        headers = {"X-Ra3Copilot-Token": get_or_create_token()}

        saved = client.post(
            "/settings/workspace/save",
            json={
                "projectId": project.id,
                "workspaceConfig": {
                    "soul_preset_id": "builtin-reliable-assistant",
                    "im_integrations": {"qq": []},
                },
            },
            headers=headers,
        )

        self.assertTrue(saved.json()["ok"])
        soul_path = Path(project.path) / "SOUL.md"
        self.assertTrue(soul_path.exists())
        self.assertIn("可靠", soul_path.read_text(encoding="utf-8"))
        self.assertEqual(saved.json()["workspaceConfig"]["soul_preset_id"], "builtin-reliable-assistant")

        removed = client.post(
            "/settings/workspace/save",
            json={
                "projectId": project.id,
                "workspaceConfig": {"soul_preset_id": "", "im_integrations": {"qq": []}},
            },
            headers=headers,
        )

        self.assertTrue(removed.json()["ok"])
        self.assertFalse(soul_path.exists())


if __name__ == "__main__":
    unittest.main()
