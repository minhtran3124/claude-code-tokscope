import plistlib
import re
import tempfile
import unittest
from pathlib import Path

from tokscope.features import service

ROOT = Path(__file__).resolve().parent.parent


class Runner:
    def __init__(self, fail=()):
        self.calls, self.fail = [], fail

    def __call__(self, argv):
        self.calls.append(argv)
        return 1 if any(f in argv for f in self.fail) else 0


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_plist_content(self):
        d = plistlib.loads(service.plist_bytes("/opt/py/bin/python3", "/Apps/tokscope/Resources", 8770, "/tmp/t.log"))
        self.assertEqual(d["Label"], "io.github.minhtran3124.tokscope")
        self.assertEqual(d["ProgramArguments"], ["/opt/py/bin/python3", "-m", "tokscope.cli", "serve", "--no-open", "--port", "8770"])
        self.assertEqual(d["EnvironmentVariables"], {"PYTHONPATH": "/Apps/tokscope/Resources"})
        self.assertTrue(d["RunAtLoad"] and d["KeepAlive"])

    def test_mac_install_writes_the_agent_and_bootstraps(self):
        r = Runner()
        msg = service.install("/py", "/root", runner=r, mac=True, home=self.home, uid=501)
        path = self.home / "Library/LaunchAgents/io.github.minhtran3124.tokscope.plist"
        self.assertEqual(plistlib.loads(path.read_bytes())["ProgramArguments"][0], "/py")
        self.assertEqual(r.calls, [["launchctl", "bootout", "gui/501", str(path)], ["launchctl", "bootstrap", "gui/501", str(path)]])
        self.assertIn("127.0.0.1:8770", msg)

    def test_mac_bootstrap_failure_raises(self):
        with self.assertRaises(RuntimeError):
            service.install("/py", "/root", runner=Runner(fail=("bootstrap",)), mac=True, home=self.home, uid=501)

    def test_mac_uninstall_and_status(self):
        r = Runner()
        self.assertEqual(service.status(r, mac=True, home=self.home, uid=501)[:2], (False, True))
        service.install("/py", "/root", runner=r, mac=True, home=self.home, uid=501)
        r.calls.clear()
        self.assertEqual(service.status(r, mac=True, home=self.home, uid=501)[:2], (True, True))
        self.assertEqual(r.calls, [["launchctl", "print", "gui/501/io.github.minhtran3124.tokscope"]])
        self.assertEqual(service.status(Runner(fail=("print",)), mac=True, home=self.home, uid=501)[2].split(" (")[0], "installed, not running")
        r.calls.clear()
        self.assertIn("removed", service.uninstall(r, mac=True, home=self.home, uid=501))
        self.assertEqual(r.calls[0][:3], ["launchctl", "bootout", "gui/501"])
        self.assertFalse(service.plist_path(self.home).exists())
        self.assertEqual(service.uninstall(r, mac=True, home=self.home, uid=501), "not installed")

    def test_linux_install_enable_uninstall_status(self):
        r = Runner()
        service.install(exe="/x/bin/tokscope", runner=r, mac=False, config=self.home)
        unit = self.home / "systemd/user/tokscope.service"
        self.assertIn("ExecStart=/x/bin/tokscope serve --no-open --port 8770\n", unit.read_text())
        self.assertEqual(r.calls, [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "tokscope.service"]])
        self.assertEqual(service.status(r, mac=False, config=self.home)[:2], (True, True))
        service.uninstall(r, mac=False, config=self.home)
        self.assertFalse(unit.exists())
        self.assertEqual(r.calls[-2:], [["systemctl", "--user", "disable", "--now", "tokscope.service"],
                                        ["systemctl", "--user", "daemon-reload"]])
        self.assertEqual(service.status(Runner(fail=("is-active",)), mac=False, config=self.home)[:2], (False, False))

    def test_linux_no_enable_only_writes(self):
        r, out = Runner(), self.home / "u.service"
        service.install(exe="/x", runner=r, mac=False, unit_file=out, enable=False)
        self.assertTrue(out.exists())
        self.assertEqual(r.calls, [])

    def test_linux_unit_text_is_what_the_scripts_wrote(self):
        self.assertEqual(service.unit_text("/opt/tokscope/resources/bin/tokscope"), (
            "[Unit]\nDescription=tokscope dashboard server (127.0.0.1:8770)\n\n[Service]\n"
            "ExecStart=/opt/tokscope/resources/bin/tokscope serve --no-open --port 8770\n"
            "Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"))
        self.assertIn('ExecStart="/a b/bin/tokscope" serve', service.unit_text("/a b/bin/tokscope", quote=True))

    def test_scripts_call_the_command_instead_of_a_heredoc(self):
        for f in ("desktop/install.sh", "desktop/build/after-install.sh"):
            text = (ROOT / f).read_text()
            self.assertRegex(text, r"tokscope\"? service install")
            self.assertNotIn("ExecStart", text)
        self.assertEqual(re.findall(r"SERVICE_PORT = (\d+)", (ROOT / "desktop/main.js").read_text()), [str(service.PORT)])


if __name__ == "__main__":
    unittest.main()
