import json
import subprocess
import sys
import unittest
from pathlib import Path

from tokscope import __version__

ROOT = Path(__file__).resolve().parent.parent


class VersionTest(unittest.TestCase):
    def test_the_mod_and_the_cli_carry_the_same_version(self):
        plugin = json.loads((ROOT / "mod" / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], __version__)

    def test_the_version_is_semver(self):
        parts = __version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))

    def test_the_changelog_has_an_entry_for_it(self):
        self.assertIn(f"## {__version__}", (ROOT / "CHANGELOG.md").read_text())

    def test_the_cli_prints_it(self):
        out = subprocess.run([sys.executable, "-m", "tokscope.cli", "--version"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), f"tokscope {__version__}")


if __name__ == "__main__":
    unittest.main()
