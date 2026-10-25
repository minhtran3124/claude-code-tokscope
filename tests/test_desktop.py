"""The macOS build pieces that can be checked on Linux: package.json, the server command, fetch-python.sh."""

import json
import shutil
import subprocess
import tempfile
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

    def test_darwin_data_folder_follows_paths_home(self):
        r = server_command(platform="darwin", root="/r", port=1, env={"TOKSCOPE_HOME": "/custom"}, home="/nohome")
        self.assertEqual(r["env"]["TOKSCOPE_HOME"], "/custom")
        with tempfile.TemporaryDirectory() as h:
            (Path(h) / ".local" / "share" / "tokscope").mkdir(parents=True)
            r = server_command(platform="darwin", root="/r", port=1, env={}, home=h)
            self.assertEqual(r["env"]["TOKSCOPE_HOME"], h + "/.local/share/tokscope")

    def test_darwin_path_has_no_duplicates(self):
        r = server_command(platform="darwin", root="/r", port=1, env={"PATH": "/opt/homebrew/bin:/usr/bin"}, home="/h")
        path = r["env"]["PATH"].split(":")
        self.assertEqual(len(path), len(set(path)))

    def test_linux_keeps_bin_tokscope(self):
        r = server_command(platform="linux", root="/opt/tokscope/resources", port=9, env={}, home="/home/m")
        self.assertEqual(r, {"cmd": ["/opt/tokscope/resources/bin/tokscope", "serve", "--no-open", "--port", "9"], "env": {}})


def mac_js(expr):
    js = "const m=require('./mac-integration');console.log(JSON.stringify(%s))" % expr
    return json.loads(subprocess.run([NODE, "-e", js], cwd=DESKTOP, capture_output=True, text=True, check=True).stdout)


@unittest.skipUnless(NODE, "node is not installed")
class MacIntegration(unittest.TestCase):
    def test_wrapper_script_runs_bundled_python(self):
        text = mac_js("m.wrapperScript('/Applications/tokscope.app/Contents/Resources')")
        self.assertTrue(text.startswith("#!/bin/sh\n"))
        self.assertIn("exec '/Applications/tokscope.app/Contents/Resources/python/bin/python3' -s -m tokscope.cli \"$@\"", text)
        self.assertIn("PYTHONPATH='/Applications/tokscope.app/Contents/Resources'", text)
        self.assertIn("Library/Application Support/tokscope", text)

    def test_wrapper_quotes_a_path_with_a_quote(self):
        text = mac_js("m.wrapperScript(\"/a b/it's\")")
        self.assertIn("'/a b/it'\\''s'", text)

    def test_wrapper_script_is_valid_sh_and_runs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            py = Path(d) / "python" / "bin"
            py.mkdir(parents=True)
            (py / "python3").write_text('#!/bin/sh\necho "py:$PYTHONPATH:$*"\n')
            (py / "python3").chmod(0o755)
            w = Path(d) / "tokscope"
            w.write_text(mac_js("m.wrapperScript(%s)" % json.dumps(d)))
            subprocess.run(["sh", "-n", str(w)], check=True)
            out = subprocess.run(["sh", str(w), "statusline"], capture_output=True, text=True, check=True).stdout
            self.assertEqual(out.strip(), "py:%s:-s -m tokscope.cli statusline" % d)

    def test_install_cli_writes_executable_wrapper(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            r = mac_js("m.installCli({root:'/R',home:%s})" % json.dumps(home))
            self.assertEqual(r["status"], "installed")
            p = Path(r["path"])
            self.assertEqual(p, Path(home) / ".local" / "bin" / "tokscope")
            self.assertTrue(os.access(p, os.X_OK))
            self.assertEqual(mac_js("m.installCli({root:'/R2',home:%s})" % json.dumps(home))["status"], "updated")
            self.assertIn("/R2/python", p.read_text())

    def test_install_cli_keeps_a_foreign_file_unless_forced(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            p = Path(home) / ".local" / "bin" / "tokscope"
            p.parent.mkdir(parents=True)
            p.write_text("#!/bin/sh\necho mine\n")
            self.assertEqual(mac_js("m.installCli({root:'/R',home:%s})" % json.dumps(home))["status"], "exists")
            self.assertEqual(p.read_text(), "#!/bin/sh\necho mine\n")
            self.assertEqual(mac_js("m.installCli({root:'/R',home:%s,force:true})" % json.dumps(home))["status"], "updated")
            self.assertIn("/R/python", p.read_text())

    def test_install_cli_never_writes_through_a_symlink(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            real = Path(home) / "clone-bin-tokscope"
            real.write_text("#!/bin/sh\necho tracked\n")
            p = Path(home) / ".local" / "bin" / "tokscope"
            p.parent.mkdir(parents=True)
            p.symlink_to(real)
            r = mac_js("m.installCli({root:'/R',home:%s})" % json.dumps(home))
            self.assertEqual((r["status"], r["symlink"]), ("exists", True))
            self.assertEqual(real.read_text(), "#!/bin/sh\necho tracked\n")
            r = mac_js("m.installCli({root:'/R',home:%s,force:true})" % json.dumps(home))
            self.assertEqual(r["status"], "updated")
            self.assertEqual(real.read_text(), "#!/bin/sh\necho tracked\n")
            self.assertFalse(p.is_symlink())
            self.assertIn("/R/python", p.read_text())
            self.assertTrue(os.access(p, os.X_OK))

    def test_service_command_install_and_uninstall(self):
        r = mac_js("m.serviceCommand({action:'install',root:'/R',home:'/h',env:{PATH:'/usr/bin'}})")
        self.assertEqual(r["cmd"], ["/R/python/bin/python3", "-s", "-m", "tokscope.cli", "service", "install",
                                    "--python", "/R/python/bin/python3", "--root", "/R",
                                    "--home", "/h/Library/Application Support/tokscope"])
        self.assertEqual(r["env"]["PYTHONPATH"], "/R")
        r = mac_js("m.serviceCommand({action:'uninstall',root:'/R',home:'/h'})")
        self.assertEqual(r["cmd"][-2:], ["service", "uninstall"])

    def test_service_flags_exist_in_the_cli(self):
        import io
        import contextlib
        from tokscope import cli
        from unittest import mock
        with contextlib.redirect_stdout(io.StringIO()) as out, mock.patch("sys.argv", ["tokscope", "service", "install", "--help"]), \
                self.assertRaises(SystemExit):
            cli.main()
        self.assertIn("--python", out.getvalue())
        self.assertIn("--root", out.getvalue())
        self.assertIn("--home", out.getvalue())

    def test_about_dock_and_path_helpers(self):
        self.assertEqual(mac_js("m.aboutOptions({version:'1.2.3'})")["applicationVersion"], "1.2.3")
        self.assertTrue(mac_js("m.shouldReopen({windowCount:0})"))
        self.assertFalse(mac_js("m.shouldReopen({windowCount:1})"))
        self.assertTrue(mac_js("m.onPath('/h/.local/bin','/usr/bin:/h/.local/bin')"))
        self.assertFalse(mac_js("m.onPath('/h/.local/bin','/usr/bin')"))

    def test_last_window_close_keeps_the_mac_app_running(self):
        self.assertFalse(mac_js("m.quitOnLastClose({platform:'darwin'})"))
        self.assertTrue(mac_js("m.quitOnLastClose({platform:'linux'})"))
        self.assertTrue(mac_js("m.quitOnLastClose({platform:'win32'})"))
        self.assertTrue(mac_js("m.shouldReopen({windowCount:0})"))
        self.assertFalse(mac_js("m.shouldReopen({windowCount:1})"))

    def test_main_js_wires_the_handlers(self):
        src = (DESKTOP / "main.js").read_text()
        for needle in ('app.on("activate"', "setAboutPanelOptions", "Start at login", "Install command line tool", "window-all-closed", "quitOnLastClose"):
            self.assertIn(needle, src)
        self.assertIn("mac-integration.js", json.loads((DESKTOP / "package.json").read_text())["build"]["files"])
        subprocess.run([NODE, "--check", str(DESKTOP / "main.js")], check=True)

    def test_file_menu_keeps_quit_off_mac(self):
        self.assertIn('{ role: isMac ? "close" : "quit" }', (DESKTOP / "main.js").read_text())


class FetchPython(unittest.TestCase):
    def test_dry_run_downloads_nothing(self):
        script = DESKTOP / "scripts" / "fetch-python.sh"
        target = DESKTOP / "python"  # a built Mac already has it, so compare before and after

        def snapshot():
            return sorted(p.stat().st_mtime_ns for p in [target, *target.rglob("*")]) if target.exists() else None

        before = snapshot()
        out = subprocess.run(["sh", str(script), "--dry-run"], capture_output=True, text=True, check=True).stdout
        self.assertIn("aarch64-apple-darwin", out)
        self.assertRegex(out, r"sha256: [0-9a-f]{64}\n")
        self.assertTrue(out.splitlines()[2].endswith("desktop/python"))
        self.assertEqual(snapshot(), before)

    def test_posix_sh_syntax(self):
        subprocess.run(["sh", "-n", str(DESKTOP / "scripts" / "fetch-python.sh")], check=True)


if __name__ == "__main__":
    unittest.main()
