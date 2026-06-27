from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

_APPDATA_DIR = tempfile.TemporaryDirectory(prefix="ra3copilot-project-instructions-")
os.environ["APPDATA"] = _APPDATA_DIR.name


class ProjectInstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        from core.user_data import projects

        self.data_root = Path(_APPDATA_DIR.name) / "Ra3Copilot"
        shutil.rmtree(self.data_root, ignore_errors=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        projects.PROJECTS_DIR = self.data_root / "projects"
        projects.PROJECT_INDEX_PATH = self.data_root / "projects.json"

    def test_loads_supported_root_instruction_files_in_order(self) -> None:
        from core.agents.project_instructions import load_project_instruction_files

        project_root = self.data_root / "workspace"
        project_root.mkdir(parents=True)
        (project_root / "USER.md").write_text("User preference", encoding="utf-8")
        (project_root / "AGENTS.md").write_text("Agent rules", encoding="utf-8")
        (project_root / "SOUL.md").write_text("Assistant soul", encoding="utf-8")
        (project_root / "notes.md").write_text("Should not load", encoding="utf-8")
        nested = project_root / "nested"
        nested.mkdir()
        (nested / "AGENTS.md").write_text("Nested should not load", encoding="utf-8")

        loaded = load_project_instruction_files(project_root)

        self.assertIn("--- project instruction: AGENTS.md ---", loaded)
        self.assertIn("--- project instruction: SOUL.md ---", loaded)
        self.assertIn("--- project instruction: USER.md ---", loaded)
        self.assertLess(loaded.index("AGENTS.md"), loaded.index("SOUL.md"))
        self.assertLess(loaded.index("SOUL.md"), loaded.index("USER.md"))
        self.assertIn("Agent rules", loaded)
        self.assertIn("Assistant soul", loaded)
        self.assertIn("User preference", loaded)
        self.assertNotIn("Should not load", loaded)
        self.assertNotIn("Nested should not load", loaded)

    def test_project_context_includes_project_instruction_files(self) -> None:
        from core.middlewares.project_context import _resolve_project_context
        from core.user_data import projects

        project = projects.create_workspace_project_at(
            "Instruction Workspace",
            str(self.data_root / "instruction-workspace"),
        )
        project_root = Path(project.path)
        (project_root / "AGENTS.md").write_text("Always check project rules.", encoding="utf-8")
        (project_root / "USER.md").write_text("Prefer concise answers.", encoding="utf-8")

        context = _resolve_project_context(project.id)

        self.assertIsNotNone(context)
        self.assertIn("Project instruction files", context or "")
        self.assertIn("Always check project rules.", context or "")
        self.assertIn("Prefer concise answers.", context or "")


if __name__ == "__main__":
    unittest.main()
