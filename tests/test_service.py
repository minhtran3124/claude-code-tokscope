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

    def test_plist_pins_the_data_folder_when_given(self):
        d = plistlib.loads(service.plist_bytes("/py", "/R", 8770, "/tmp/t.log", data_home="/D"))
        self.assertEqual(d["EnvironmentVariables"], {"PYTHONPATH": "/R", "TOKSCOPE_HOME": "/D", "PYTHONNOUSERSITE": "1"})
        self.assertEqual(d["ProgramArguments"][:3], ["/py", "-s", "-m"])
        r = Runner()
        service.install("/py", "/R", runner=r, mac=True, home=self.home, uid=501, data_home="/D")
        path = service.plist_path(self.home)
        self.assertEqual(plistlib.loads(path.read_bytes())["EnvironmentVariables"]["TOKSCOPE_HOME"], "/D")

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


class ServiceControlTest(unittest.TestCase):
    """state, stop, start and set_autostart: what the Settings card calls."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name)
        self.unit = service.unit_path(self.config)

    def write_unit(self):
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text("[Unit]\n")

    def test_state_without_a_service_manager(self):
        s = service.state(Runner(), mac=False, config=self.config, which=lambda _: None)
        self.assertFalse(s["supported"])

    def test_state_not_installed_then_running_and_enabled(self):
        which = lambda _: "/bin/x"
        s = service.state(Runner(), mac=False, config=self.config, which=which)
        self.assertEqual((s["supported"], s["installed"], s["running"], s["autostart"]), (True, False, True, False))
        self.write_unit()
        s = service.state(Runner(), mac=False, config=self.config, which=which)
        self.assertEqual((s["installed"], s["running"], s["autostart"]), (True, True, True))
        s = service.state(Runner(fail=("is-enabled",)), mac=False, config=self.config, which=which)
        self.assertFalse(s["autostart"])

    def test_state_on_mac_has_no_autostart_switch(self):
        s = service.state(Runner(), mac=True, home=self.config, which=lambda _: "/bin/x")
        self.assertIsNone(s["autostart"])

    def test_stop_and_start_need_an_installed_service(self):
        for fn in (service.stop, service.start):
            with self.assertRaises(RuntimeError):
                fn(Runner(), mac=False, config=self.config)

    def test_stop_start_and_autostart_call_systemctl(self):
        self.write_unit()
        r = Runner()
        service.stop(r, mac=False, config=self.config)
        service.start(r, mac=False, config=self.config)
        service.set_autostart(True, r, mac=False, config=self.config)
        service.set_autostart(False, r, mac=False, config=self.config)
        self.assertEqual(r.calls, [["systemctl", "--user", "stop", "tokscope.service"], ["systemctl", "--user", "start", "tokscope.service"],
                                   ["systemctl", "--user", "enable", "tokscope.service"], ["systemctl", "--user", "disable", "tokscope.service"]])
        with self.assertRaises(RuntimeError):
            service.stop(Runner(fail=("stop",)), mac=False, config=self.config)

    def test_mac_stop_start_use_launchctl_and_autostart_is_refused(self):
        plist = service.plist_path(self.config)
        plist.parent.mkdir(parents=True)
        plist.write_bytes(b"x")
        r = Runner()
        service.stop(r, mac=True, home=self.config, uid=501)
        service.start(r, mac=True, home=self.config, uid=501)
        self.assertEqual([c[:3] for c in r.calls], [["launchctl", "bootout", "gui/501"], ["launchctl", "bootstrap", "gui/501"]])
        with self.assertRaises(RuntimeError):
            service.set_autostart(True, r, mac=True, home=self.config)
