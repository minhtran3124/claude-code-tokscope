"""`tokscope service`: keep `tokscope serve` running from login. launchd on macOS, a systemd user unit on Linux.

Opt-in only: nothing is enabled for other users. The runner (argv list in, exit code out) is replaceable for tests."""
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "io.github.minhtran3124.tokscope"
PORT = 8770  # the same number as SERVICE_PORT in desktop/main.js
CHECKOUT = Path(__file__).resolve().parents[2]


def run(argv):
    try:
        return subprocess.run(argv, capture_output=True).returncode
    except OSError:
        return 127


def is_mac():
    return sys.platform == "darwin"


def plist_path(home=None):
    return Path(home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def unit_path(config=None):
    return Path(config or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / "tokscope.service"


def _uid(uid):
    return os.getuid() if uid is None else uid


def plist_bytes(python, root, port=PORT, log=None, data_home=None):
    """The launchd agent: `python -m tokscope.cli serve` with PYTHONPATH at the folder that holds the tokscope package.
    `data_home` (the app passes its data folder) pins TOKSCOPE_HOME and isolates the user site like the app launch."""
    log = str(log or Path.home() / "Library" / "Logs" / "tokscope.log")
    env = {"PYTHONPATH": str(root)}
    if data_home:
        env.update(TOKSCOPE_HOME=str(data_home), PYTHONNOUSERSITE="1")
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(python), *(["-s"] if data_home else []), "-m", "tokscope.cli", "serve", "--no-open", "--port", str(port)],
        "EnvironmentVariables": env,
        "RunAtLoad": True, "KeepAlive": True, "StandardOutPath": log, "StandardErrorPath": log})


def unit_text(exe, port=PORT, quote=False):
    """The systemd user unit; `quote` wraps the executable path in double quotes (needed when the path may hold spaces)."""
    exe = f'"{exe}"' if quote else exe
    return (f"[Unit]\nDescription=tokscope dashboard server (127.0.0.1:{port})\n\n[Service]\n"
            f"ExecStart={exe} serve --no-open --port {port}\nRestart=on-failure\nRestartSec=5\n\n"
            "[Install]\nWantedBy=default.target\n")


def install(python=None, root=None, exe=None, port=PORT, runner=run, mac=None, home=None, config=None, unit_file=None,
            enable=True, quote=False, uid=None, data_home=None):
    """Write the service file and start it. Returns a one-line message; raises RuntimeError when the manager refuses."""
    mac = is_mac() if mac is None else mac
    if mac:
        path = plist_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plist_bytes(python or sys.executable, root or CHECKOUT, port, data_home=data_home))
        domain = f"gui/{_uid(uid)}"
        runner(["launchctl", "bootout", domain, str(path)])  # replace a loaded copy; fails harmlessly when none is loaded
        if runner(["launchctl", "bootstrap", domain, str(path)]) != 0:
            raise RuntimeError(f"launchctl bootstrap {domain} failed; the agent is written to {path}")
        return f"started {LABEL} on 127.0.0.1:{port} (stop it with: tokscope service uninstall)"
    path = Path(unit_file) if unit_file else unit_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(exe or CHECKOUT / "bin" / "tokscope", port, quote))
    if not enable:
        return f"wrote {path}"
    runner(["systemctl", "--user", "daemon-reload"])
    if runner(["systemctl", "--user", "enable", "--now", "tokscope.service"]) != 0:
        raise RuntimeError(f"systemctl --user enable --now tokscope.service failed; the unit is written to {path}")
    return f"started tokscope.service on 127.0.0.1:{port} (stop it with: systemctl --user disable --now tokscope.service)"


def uninstall(runner=run, mac=None, home=None, config=None, uid=None):
    mac = is_mac() if mac is None else mac
    path = plist_path(home) if mac else unit_path(config)
    if mac:
        runner(["launchctl", "bootout", f"gui/{_uid(uid)}", str(path)])
    else:
        runner(["systemctl", "--user", "disable", "--now", "tokscope.service"])
    existed = path.exists()
    path.unlink(missing_ok=True)
    if not mac:
        runner(["systemctl", "--user", "daemon-reload"])
    return f"removed {path}" if existed else "not installed"


def status(runner=run, mac=None, home=None, config=None, uid=None):
    """(installed, running, text)"""
    mac = is_mac() if mac is None else mac
    path = plist_path(home) if mac else unit_path(config)
    installed = path.exists()
    if mac:
        running = runner(["launchctl", "print", f"gui/{_uid(uid)}/{LABEL}"]) == 0
    else:
        running = runner(["systemctl", "--user", "is-active", "--quiet", "tokscope.service"]) == 0
    state = "running" if running else "installed, not running" if installed else "not installed"
    return installed, running, f"{state} ({path})"


def state(runner=run, mac=None, home=None, config=None, uid=None, which=shutil.which):
    """What the Settings card shows: supported (the service manager exists), installed, running and autostart
    (starts at login; None on macOS, where installed means it starts at login and the app's menu turns it on or off)."""
    mac = is_mac() if mac is None else mac
    if not which("launchctl" if mac else "systemctl"):
        return {"supported": False, "installed": False, "running": False, "autostart": None, "mac": mac}
    installed, running, _ = status(runner, mac, home, config, uid)
    autostart = None if mac else installed and runner(["systemctl", "--user", "is-enabled", "--quiet", "tokscope.service"]) == 0
    return {"supported": True, "installed": installed, "running": running, "autostart": autostart, "mac": mac}


def _need_installed(mac, home, config):
    if not (plist_path(home) if mac else unit_path(config)).exists():
        raise RuntimeError("the service is not installed")


def stop(runner=run, mac=None, home=None, config=None, uid=None):
    """Stop it now; it stays installed, so it starts again at the next login when autostart is on."""
    mac = is_mac() if mac is None else mac
    _need_installed(mac, home, config)
    argv = (["launchctl", "bootout", f"gui/{_uid(uid)}", str(plist_path(home))] if mac
            else ["systemctl", "--user", "stop", "tokscope.service"])
    if runner(argv) != 0:
        raise RuntimeError("could not stop the service")
    return "stopped"


def start(runner=run, mac=None, home=None, config=None, uid=None):
    mac = is_mac() if mac is None else mac
    _need_installed(mac, home, config)
    argv = (["launchctl", "bootstrap", f"gui/{_uid(uid)}", str(plist_path(home))] if mac
            else ["systemctl", "--user", "start", "tokscope.service"])
    if runner(argv) != 0:
        raise RuntimeError("could not start the service")
    return "started"


def set_autostart(on, runner=run, mac=None, home=None, config=None):
    """Linux: enable or disable the unit for the next login; it does not start or stop it now."""
    if (is_mac() if mac is None else mac):
        raise RuntimeError("on macOS use File > Start at login in the app")
    _need_installed(False, home, config)
    if runner(["systemctl", "--user", "enable" if on else "disable", "tokscope.service"]) != 0:
        raise RuntimeError("could not change the service")
    return "enabled" if on else "disabled"
