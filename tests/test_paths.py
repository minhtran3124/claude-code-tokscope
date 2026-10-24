import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope import paths


class PathsTest(unittest.TestCase):
    def test_a_checkout_keeps_its_data_in_the_repo(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOKSCOPE_HOME", None)
            self.assertEqual(paths.home(), paths.SRC)

    def test_tokscope_home_wins(self):
        with mock.patch.dict(os.environ, {"TOKSCOPE_HOME": "/tmp/tk-home"}):
            self.assertEqual(paths.home(), Path("/tmp/tk-home"))

    def test_an_installed_package_uses_the_xdg_data_folder(self):
        # an installed package has no pyproject.toml beside it
        with tempfile.TemporaryDirectory() as fake, mock.patch.object(paths, "SRC", Path(fake)), \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg"}):
            os.environ.pop("TOKSCOPE_HOME", None)
            self.assertEqual(paths.home(), Path("/tmp/xdg/tokscope"))

    def test_a_phases_file_in_the_data_home_overrides_the_shipped_one(self):
        with tempfile.TemporaryDirectory() as h, mock.patch.dict(os.environ, {"TOKSCOPE_HOME": h}):
            self.assertEqual(paths.phases(), paths.ASSETS / "phases.json")
            (Path(h) / "phases.json").write_text("{}")
            self.assertEqual(paths.phases(), Path(h) / "phases.json")

    def test_the_db_folder_is_created_on_first_use(self):
        with tempfile.TemporaryDirectory() as h, mock.patch.dict(os.environ, {"TOKSCOPE_HOME": h}):
            self.assertTrue(paths.db().parent.is_dir())

    def test_claude_config_dir_lists_projects_folders(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/x, /y/"}):
            self.assertEqual(paths.projects_dirs(), [Path("/x/projects"), Path("/y/projects")])

    def test_an_explicit_folder_wins_over_the_env(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/x"}):
            self.assertEqual(paths.projects_dirs("/p"), [Path("/p")])

    def test_the_xdg_and_dot_claude_folders_are_both_used_when_present(self):
        with tempfile.TemporaryDirectory() as h, mock.patch.dict(os.environ, {"HOME": h}), \
                mock.patch.object(Path, "home", return_value=Path(h)):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertEqual(paths.projects_dirs(), [Path(h) / ".claude" / "projects"])  # none exist: the default
            (Path(h) / ".config/claude/projects").mkdir(parents=True)
            self.assertEqual(paths.projects_dirs(), [Path(h) / ".config/claude/projects"])
            (Path(h) / ".claude/projects").mkdir(parents=True)
            self.assertEqual(paths.projects_dirs(), [Path(h) / ".config/claude/projects", Path(h) / ".claude/projects"])


if __name__ == "__main__":
    unittest.main()
