"""The line icons of the report and the dashboard: one 24 px path each, 2 px stroke, round caps, in the text colour.
Inline SVG, so no page asks another site for an icon."""

PATHS = {
    "home": "M4 11l8-7 8 7M6 10v10h12V10",
    "list": "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01",
    "pivot": "M4 4h16v16H4zM4 9h16M9 4v16M13 13h4M13 16h4",
    "folder": "M3 6h7l2 2h9v11H3z",
    "puzzle": "M10 4h4v3a2 2 0 104 0v3h-3a2 2 0 100 4h3v6H4v-6h3a2 2 0 100-4H4V4z",
    "bolt": "M13 3L5 14h6l-1 7 8-11h-6z",
    "flask": "M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3M7.5 15h9",
    "cloud": "M7 18a4 4 0 01-.5-8 6 6 0 0111.5 1.5A3.5 3.5 0 0117.5 18z",
    "sliders": "M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6",
}
# the icon beside each page in the menu
PAGE_ICON = {"overview": "home", "sessions": "list", "breakdowns": "pivot", "projects": "folder", "library": "puzzle",
             "optimize": "bolt", "benchmarks": "flask", "managed": "cloud", "settings": "sliders"}


def icon(name, size=18):
    return (f'<svg class="ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{PATHS[name]}"/></svg>')
