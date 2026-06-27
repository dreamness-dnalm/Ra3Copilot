from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.user_data.project_files import delete_project_item
from core.user_data.projects import ProjectEntry


class ProjectFilesDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ra3copilot-files-")
        self.root = Path(self.temp_dir.name)
        self.project = ProjectEntry(
            id="project",
            name="Project",
            path=str(self.root),
            kind="workspace",
            created_at="",
            last_opened_at="",
            hidden=False,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_permanent_delete_removes_file(self) -> None:
        target = self.root / "note.md"
        target.write_text("hello", encoding="utf-8")

        delete_project_item(self.project, "note.md", "permanent")

        self.assertFalse(target.exists())

    def test_trash_delete_uses_recycle_bin_helper(self) -> None:
        target = self.root / "note.md"
        target.write_text("hello", encoding="utf-8")

        with patch("core.user_data.project_files._move_to_recycle_bin") as move_to_recycle_bin:
            delete_project_item(self.project, "note.md", "trash")

        move_to_recycle_bin.assert_called_once_with(target.resolve(strict=False))
        self.assertTrue(target.exists())

    def test_unknown_delete_mode_is_rejected(self) -> None:
        target = self.root / "note.md"
        target.write_text("hello", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "未知删除方式"):
            delete_project_item(self.project, "note.md", "sideways")
