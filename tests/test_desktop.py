"""The macOS build pieces that can be checked on Linux: package.json, the server command, fetch-python.sh."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent.parent / "desktop"
NODE = shutil.which("node")


def server_command(**kw):
    js = "console.log(JSON.stringify(require('./server-command').serverCommand(%s)))" % json.dumps(kw)
    out = subprocess.run([NODE, "-e", js], cwd=DESKTOP, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class MacPackage(unittest.TestCase):
    def setUp(self):
        self.pkg = json.loads((DESKTOP / "package.json").read_text())

    def test_mac_target_is_arm64_dmg_and_zip(self):
        mac = self.pkg["build"]["mac"]
        self.assertEqual({(t["target"], tuple(t["arch"])) for t in mac["target"]},
                         {("dmg", ("arm64",)), ("zip", ("arm64",))})
        self.assertIn("dist:mac", self.pkg["scripts"])
        self.assertIn({"from": "python", "to": "python"}, mac["extraResources"])
        for key in ("entitlements", "entitlementsInherit"):
            self.assertTrue((DESKTOP / mac[key]).is_file())

    def test_packaged_files_exist(self):
        for f in self.pkg["build"]["files"]:
            self.assertTrue((DESKTOP / f).is_file(), f)

    def test_entitlements_is_a_plist(self):
        self.assertIn("<plist", (DESKTOP / "build" / "entitlements.mac.plist").read_text())


@unittest.skipUnless(NODE, "node is not installed")
class ServerCommand(unittest.TestCase):
    def test_darwin_uses_bundled_python(self):
        r = server_command(platform="darwin", root="/App/Resources", port=1234, env={"PATH": "/usr/bin:/bin"}, home="/Users/m")
        self.assertEqual(r["cmd"], ["/App/Resources/python/bin/python3", "-s", "-m", "tokscope.cli", "serve", "--no-open", "--port", "1234"])
        self.assertEqual(r["env"]["PYTHONPATH"], "/App/Resources")
        self.assertEqual(r["env"]["PYTHONNOUSERSITE"], "1")
        self.assertEqual(r["env"]["TOKSCOPE_HOME"], "/Users/m/Library/Application Support/tokscope")
        path = r["env"]["PATH"].split(":")
        self.assertEqual(path[:2], ["/usr/bin", "/bin"])
        self.assertIn("/opt/homebrew/bin", path)
        self.assertIn("/Users/m/.local/bin", path)

    def test_darwin_path_has_no_duplicates(self):
        r = server_command(platform="darwin", root="/r", port=1, env={"PATH": "/opt/homebrew/bin:/usr/bin"}, home="/h")
        path = r["env"]["PATH"].split(":")
        self.assertEqual(len(path), len(set(path)))

    def test_linux_keeps_bin_tokscope(self):
        r = server_command(platform="linux", root="/opt/tokscope/resources", port=9, env={}, home="/home/m")
        self.assertEqual(r, {"cmd": ["/opt/tokscope/resources/bin/tokscope", "serve", "--no-open", "--port", "9"], "env": {}})


class FetchPython(unittest.TestCase):
    def test_dry_run_downloads_nothing(self):
        script = DESKTOP / "scripts" / "fetch-python.sh"
        out = subprocess.run(["sh", str(script), "--dry-run"], capture_output=True, text=True, check=True).stdout
        self.assertIn("aarch64-apple-darwin", out)
        self.assertRegex(out, r"sha256: [0-9a-f]{64}\n")
        self.assertTrue(out.splitlines()[2].endswith("desktop/python"))
        self.assertFalse((DESKTOP / "python").exists())

    def test_posix_sh_syntax(self):
        subprocess.run(["sh", "-n", str(DESKTOP / "scripts" / "fetch-python.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
