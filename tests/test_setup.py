import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = str(ROOT / "mod")


class SetupScriptTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.settings = self.home / ".claude" / "settings.json"
        self.link = self.home / ".local" / "bin" / "tokscope"

    def run_setup(self, *args):
        env = {**os.environ, "HOME": str(self.home), "TOKSCOPE_HOME": str(self.home / "data")}
        env.pop("CLAUDE_CONFIG_DIR", None)
        return subprocess.run(["sh", str(ROOT / "setup.sh"), *args], env=env, capture_output=True, text=True, check=True)

    def dirs(self):
        env = json.loads(self.settings.read_text())["env"]
        return env["CLAUDE_CODE_PLUGIN_DIRS"].split(os.pathsep)

    def test_it_links_the_cli_and_registers_the_mod(self):
        self.run_setup()
        self.assertEqual(self.link.resolve(), ROOT / "bin" / "tokscope")
        self.assertEqual(self.dirs(), [MOD])

    def test_the_linked_cli_runs(self):
        self.run_setup()
        out = subprocess.run([str(self.link), "--version"], capture_output=True, text=True, env={**os.environ, "HOME": str(self.home), "TOKSCOPE_HOME": str(self.home / "data")})
        self.assertTrue(out.stdout.startswith("tokscope "), out.stderr)

    def test_it_keeps_other_settings_and_folders_and_a_backup(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"model": "sonnet", "env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/other", "A": "1"}}))
        self.run_setup()
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["model"], "sonnet")
        self.assertEqual(data["env"]["A"], "1")
        self.assertEqual(self.dirs(), ["/x/other", MOD])
        self.assertTrue(self.settings.with_name("settings.json.bak").exists())

    def test_a_second_run_changes_nothing(self):
        self.run_setup()
        first = self.settings.read_text()
        self.run_setup()
        self.assertEqual(self.settings.read_text(), first)
        self.assertEqual(self.dirs(), [MOD])

    def test_uninstall_removes_only_its_own_entries(self):
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/other"}}))
        self.run_setup()
        self.run_setup("--uninstall")
        self.assertFalse(self.link.exists() or self.link.is_symlink())
        self.assertEqual(self.dirs(), ["/x/other"])

    def test_uninstall_leaves_a_link_that_points_elsewhere(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to("/bin/true")
        self.run_setup("--uninstall")
        self.assertTrue(self.link.is_symlink())


class LauncherCwdTest(unittest.TestCase):
    def test_a_relative_out_lands_in_the_callers_folder(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "TOKSCOPE_HOME": str(Path(d) / "data")}
            r = subprocess.run([str(ROOT / "bin" / "tokscope"), "report", "--out", "x.html"], cwd=d, env=env, capture_output=True, text=True)
            self.assertTrue((Path(d) / "x.html").exists(), r.stdout + r.stderr)
            self.assertFalse((ROOT / "x.html").exists())


if __name__ == "__main__":
    unittest.main()
