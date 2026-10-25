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


class ToolTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home, self.empty = Path(tmp.name) / "home", Path(tmp.name) / "path"  # an empty PATH: nothing else is found
        self.empty.mkdir()
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "PATH": str(self.empty)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def exe(self, folder, name):
        path = Path(folder) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return str(path)

    def test_a_tool_in_a_user_bin_folder_is_found_without_it_on_path(self):
        self.assertIsNone(paths.tool("claude"))
        for folder in (".local/bin", "bin"):
            exe = self.exe(self.home / folder, "claude")
            self.assertEqual(paths.tool("claude"), exe)
            os.unlink(exe)

    def test_a_tool_on_path_wins_over_the_extra_folders(self):
        self.exe(self.home / ".local/bin", "ant")
        on_path = self.exe(self.empty, "ant")
        self.assertEqual(paths.tool("ant"), on_path)

    def test_first_folders_win_over_path(self):
        self.exe(self.empty, "claude")
        own = self.exe(self.home / ".local/bin", "claude")
        self.assertEqual(paths.tool("claude", first=paths.CLAUDE_FIRST), own)

    def test_homebrew_and_usr_local_style_folders_are_searched(self):
        with mock.patch.object(paths, "TOOL_DIRS", (str(self.home / "opt/homebrew/bin"), str(self.home / "usr/local/bin"))):
            exe = self.exe(self.home / "usr/local/bin", "ant")
            self.assertEqual(paths.tool("ant"), exe)

    def test_on_darwin_apples_git_stub_is_skipped_when_xcode_select_fails(self):
        calls = []
        fail = lambda cmd, **kw: calls.append(cmd) or mock.Mock(returncode=2)  # noqa: E731
        with mock.patch.object(paths.shutil, "which", lambda n, path=None: "/usr/bin/git" if path is None else None):
            self.assertIsNone(paths.tool("git", platform="darwin", run=fail))
            self.assertEqual(calls, [["xcode-select", "-p"]])
            ok = lambda cmd, **kw: mock.Mock(returncode=0)  # noqa: E731
            self.assertEqual(paths.tool("git", platform="darwin", run=ok), "/usr/bin/git")
            self.assertIsNone(paths.tool("git", platform="darwin", run=mock.Mock(side_effect=FileNotFoundError)))

    def test_a_real_git_in_a_extra_folder_replaces_the_stub(self):
        which = lambda n, path=None: "/usr/bin/git" if path is None else "/opt/homebrew/bin/git"  # noqa: E731
        with mock.patch.object(paths.shutil, "which", which):
            got = paths.tool("git", platform="darwin", run=lambda *a, **k: mock.Mock(returncode=2))
        self.assertEqual(got, "/opt/homebrew/bin/git")

    def test_linux_and_other_tools_never_run_xcode_select(self):
        run = mock.Mock()
        with mock.patch.object(paths.shutil, "which", lambda n, path=None: f"/usr/bin/{n}"):
            self.assertEqual(paths.tool("git", platform="linux", run=run), "/usr/bin/git")
            self.assertEqual(paths.tool("claude", platform="darwin", run=run), "/usr/bin/claude")
        run.assert_not_called()

    def test_no_git_date_when_git_is_unavailable(self):
        from tokscope.core import skills
        with mock.patch.object(skills.paths, "tool", return_value=None):
            self.assertIsNone(skills._git_date(self.home))


if __name__ == "__main__":
    unittest.main()
