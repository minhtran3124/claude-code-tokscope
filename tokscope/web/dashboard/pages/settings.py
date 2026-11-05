"""The Settings page: the look and the time zone (saved in this browser by the page script), the privacy level of this
server, the keyboard shortcuts. The controls carry the data-set-* attributes that report.JS_CORE reads, so they work
on any page that holds them."""

import html

from .... import __version__


def _seg(label_id, label, buttons):
    chips = "".join(f'<button type="button" class="chip" data-set-{attr}="{value}" aria-pressed="false">{text}</button>'
                    for attr, value, text in buttons)
    return f'<div class="segctl" role="group" aria-labelledby="{label_id}">{chips}</div>'


def _row(label_id, label, note, control):
    return (f'<div class="setrow"><div><b id="{label_id}">{label}</b><p class="note">{note}</p></div>{control}</div>')


def page_settings(level):
    look = (_row("set-theme", "Theme", "Auto follows your system.",
                 _seg("set-theme", "Theme", [("theme", m, m.capitalize()) for m in ("light", "dark", "auto")]))
            + _row("set-skin", "Design", "Ink is the current look. Classic is the older one.",
                   _seg("set-skin", "Design", [("skin", m, m.capitalize()) for m in ("ink", "classic")]))
            + _row("set-tz", "Time zone", "Times are stored in UTC.",
                   _seg("set-tz", "Time zone", [("tz", "local", "Local"), ("tz", "utc", "UTC")])))
    data = (_row("set-privacy", "Privacy level", "Names and text follow it. It is set when the server starts: "
                 "<code>tokscope serve --privacy</code>.", f'<span class="pill-static">{html.escape(level)}</span>')
            + _row("set-version", "Version", "Python standard library only. Works offline.",
                   f'<span class="pill-static">{html.escape(__version__)}</span>'))
    keys = "".join(f"<div><span>{what}</span><kbd>{key}</kbd></div>" for key, what in (
        ("t", "Light or dark theme"), ("s", "Classic or Ink design"), ("g", "Back to the top"),
        ("/", "Filter sessions (Sessions page)"), ("?", "Show this list")))
    return (f'<section class="card" id="set-look"><h2>Appearance</h2><div class="setrows">{look}</div></section>'
            f'<section class="card" id="set-data"><h2>Data</h2><div class="setrows">{data}</div></section>'
            f'<section class="card" id="set-keys"><h2>Keyboard</h2><div class="setrows keyrows">{keys}</div>'
            '<p><button type="button" class="chip" id="keys-btn">Show shortcuts</button></p></section>')
