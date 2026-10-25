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

    def _installed(self, platform, home, env=None):
        with mock.patch.object(paths, "SRC", Path(home) / "nosrc"), mock.patch.object(Path, "home", return_value=Path(home)), \
                mock.patch.object(paths.sys, "platform", platform), mock.patch.dict(os.environ, env or {}):
            os.environ.pop("TOKSCOPE_HOME", None)
            if not env:
                os.environ.pop("XDG_DATA_HOME", None)
            return paths.home()

    def test_macos_new_install_uses_application_support(self):
        with tempfile.TemporaryDirectory() as h:
            self.assertEqual(self._installed("darwin", h), Path(h) / "Library/Application Support/tokscope")

    def test_macos_keeps_an_existing_local_share_folder(self):
        with tempfile.TemporaryDirectory() as h:
            (Path(h) / ".local/share/tokscope").mkdir(parents=True)
            self.assertEqual(self._installed("darwin", h), Path(h) / ".local/share/tokscope")

    def test_linux_is_unchanged(self):
        with tempfile.TemporaryDirectory() as h:
            self.assertEqual(self._installed("linux", h), Path(h) / ".local/share/tokscope")

    def test_xdg_and_tokscope_home_still_win_on_macos(self):
        with tempfile.TemporaryDirectory() as h:
            self.assertEqual(self._installed("darwin", h, {"XDG_DATA_HOME": "/tmp/xdg"}), Path("/tmp/xdg/tokscope"))
            with mock.patch.dict(os.environ, {"TOKSCOPE_HOME": "/tmp/tk"}), mock.patch.object(paths.sys, "platform", "darwin"):
                self.assertEqual(paths.home(), Path("/tmp/tk"))

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
