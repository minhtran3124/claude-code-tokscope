"""The Settings page: the look and the time zone (saved in this browser by the page script), the privacy level of this
server, the keyboard shortcuts. The controls carry the data-set-* attributes that report.JS_CORE reads, so they work
on any page that holds them."""

import html

from .... import __version__
from ....features import service


def _seg(label_id, buttons):
    chips = "".join(f'<button type="button" class="chip" data-set-{attr}="{value}" aria-pressed="false">{text}</button>'
                    for attr, value, text in buttons)
    return f'<div class="segctl" role="group" aria-labelledby="{label_id}">{chips}</div>'


def _row(label_id, label, note, control):
    return (f'<div class="setrow"><div><b id="{label_id}">{label}</b><p class="note">{note}</p></div>{control}</div>')


def _service_card(level, svc):
    """The Background service card: status, Stop or Start, and Start automatically. Writes need the full level;
    the page script (SETTINGS_JS) sends them."""
    if not svc["supported"]:
        status, note, act = "Not available", "This system has no systemd (Linux) or launchd (macOS) user manager.", ""
    elif not svc["installed"]:
        status, note = "Not installed", "tokscope serve is not kept running. Turn it on to start it at every login."
        act = '<button type="button" class="primary" data-svc="install">Install and start</button>' if not svc["mac"] else ""
        note += " On macOS use File > Start at login in the app." if svc["mac"] else ""
    else:
        status = "Running" if svc["running"] else "Stopped"
        note = ("Runs <code>tokscope serve</code> for your user on 127.0.0.1:8770. If this page is served by it, "
                "Stop ends this page too." if svc["running"] else "Start it again, or run <code>tokscope serve</code> by hand.")
        act = (f'<button type="button" class="btn" data-svc="{"stop" if svc["running"] else "start"}">'
               f'{"Stop" if svc["running"] else "Start"}</button>')
    if level != "full":
        act = ""
        note += " Changing it needs the full privacy level."
    rows = _row("svc-status", "Status", note, f'<span class="svcctl"><span class="pill-static" id="svc-state">{status}</span>{act}</span>')
    if svc["autostart"] is not None:
        on = "checked" if svc["autostart"] else ""
        off = "" if level == "full" and svc["installed"] else "disabled"
        rows += _row("svc-auto", "Start automatically", "Starts the service at every login.",
                     f'<label><input type="checkbox" id="svc-auto-box" aria-labelledby="svc-auto" {on} {off}></label>')
    return ('<section class="card" id="set-service"><h2>Background service</h2>'
            f'<div class="setrows">{rows}</div><p class="note err" id="svc-err" role="alert" hidden></p></section>')


def page_settings(level, svc=None):
    look = (_row("set-theme", "Theme", "Auto follows your system.",
                 _seg("set-theme", [("theme", m, m.capitalize()) for m in ("light", "dark", "auto")]))
            + _row("set-tz", "Time zone", "Times are stored in UTC.",
                   _seg("set-tz", [("tz", "local", "Local"), ("tz", "utc", "UTC")])))
    data = (_row("set-privacy", "Privacy level", "Names and text follow it. It is set when the server starts: "
                 "<code>tokscope serve --privacy</code>.", f'<span class="pill-static">{html.escape(level)}</span>')
            + _row("set-version", "Version", "Python standard library only. Works offline.",
                   f'<span class="pill-static">{html.escape(__version__)}</span>'))
    keys = "".join(f"<div><span>{what}</span><kbd>{key}</kbd></div>" for key, what in (
        ("t", "Light or dark theme"), ("g", "Back to the top"),
        ("/", "Filter sessions (Sessions page)"), ("?", "Show this list")))
    svc = service.state() if svc is None else svc
    return (f'<section class="card" id="set-look"><h2>Appearance</h2><div class="setrows">{look}</div></section>'
            f'<section class="card" id="set-data"><h2>Data</h2><div class="setrows">{data}</div></section>'
            + _service_card(level, svc) +
            f'<section class="card" id="set-keys"><h2>Keyboard</h2><div class="setrows keyrows">{keys}</div>'
            '<p><button type="button" class="chip" id="keys-btn">Show shortcuts</button></p></section>')
