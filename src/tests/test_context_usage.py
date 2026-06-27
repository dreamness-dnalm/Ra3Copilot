from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

_APPDATA_DIR = tempfile.TemporaryDirectory(prefix="ra3copilot-context-usage-")
os.environ["APPDATA"] = _APPDATA_DIR.name


class ContextUsageTests(unittest.TestCase):
    def setUp(self) -> None:
        from core.user_data import projects

        self.data_root = Path(_APPDATA_DIR.name) / "Ra3Copilot"
        shutil.rmtree(self.data_root, ignore_errors=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        projects.PROJECTS_DIR = self.data_root / "projects"
        projects.PROJECT_INDEX_PATH = self.data_root / "projects.json"

    def test_estimate_context_usage_splits_loaded_sources(self) -> None:
        from core.context_usage import estimate_context_usage
        from core.user_data import projects
        from core.user_data.history import append_message

        project = projects.create_workspace_project_at(
            "Context Workspace",
            str(self.data_root / "context-workspace"),
        )
        project_root = Path(project.path)
        (project_root / "AGENTS.md").write_text("Always follow workspace rules.", encoding="utf-8")
        skill_dir = project_root / ".agent" / "skills" / "demo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("Use the demo skill when relevant.", encoding="utf-8")
        append_message(project, "thread-1", "user", "Please inspect the project.")
        append_message(project, "thread-1", "assistant", "I will inspect it.")

        usage = estimate_context_usage(
            project.model_dump(),
            thread_id="thread-1",
            agent_mode="universal",
            draft_text="Current draft text.",
        )

        sections = {section["id"]: section for section in usage["sections"]}
        self.assertTrue(usage["estimate"])
        self.assertGreater(usage["usedTokens"], 0)
        self.assertGreater(usage["maxTokens"], 0)
        self.assertGreater(sections["system"]["tokens"], 0)
        self.assertGreater(sections["tools"]["tokens"], 0)
        self.assertGreater(sections["skills"]["tokens"], 0)
        self.assertGreater(sections["instructions"]["tokens"], 0)
        self.assertGreater(sections["project"]["tokens"], 0)
        self.assertGreater(sections["history"]["tokens"], 0)
        self.assertGreater(sections["draft"]["tokens"], 0)

    def test_context_usage_api_returns_usage_payload(self) -> None:
        from fastapi.testclient import TestClient

        from core.user_data import projects
        from daemon.locking import get_or_create_token
        from daemon.server import create_app

        project = projects.create_workspace_project_at(
            "API Context Workspace",
            str(self.data_root / "api-context-workspace"),
        )
        client = TestClient(create_app(), client=("127.0.0.1", 50104))
        response = client.post(
            "/context/usage",
            json={
                "project": project.model_dump(),
                "threadId": "",
                "agentMode": "assistant",
                "draftText": "hello",
            },
            headers={"X-Ra3Copilot-Token": get_or_create_token()},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIs(body.get("ok"), True)
        self.assertIn("usage", body)
        self.assertGreater(body["usage"]["usedTokens"], 0)
        self.assertTrue(any(section["id"] == "draft" for section in body["usage"]["sections"]))


if __name__ == "__main__":
    unittest.main()
