"""The two typefaces of the report and the dashboard: IBM Plex Mono for labels, controls,
numbers and code; Be Vietnam Pro for sentences and names.

Both are SIL Open Font License 1.1. The latin and vietnamese subsets ship in tokscope/fonts/, so no page asks another
site for a font. The report embeds them (one file that works offline and when shared); the dashboard serves them from
/fonts/ with a long cache."""

import base64
import re
from functools import lru_cache

from . import paths

SANS = "'Be Vietnam Pro',system-ui,sans-serif"
MONO = "'IBM Plex Mono',ui-monospace,monospace"

RANGES = {
    "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    "vietnamese": "U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,U+1EA0-1EF9,U+20AB",
}
FACES = [("Be Vietnam Pro", w) for w in (400, 500, 600, 700)] + [("IBM Plex Mono", w) for w in (400, 500, 600)]
FILE = re.compile(r"^[A-Za-z]+-\d{3}-[a-z]+\.woff2$")


def _name(family, weight, subset):
    return f"{family.replace(' ', '')}-{weight}-{subset}.woff2"


@lru_cache(maxsize=None)
def read(name):
    """The bytes of a shipped font file, or None when the name is not one of them."""
    path = paths.PACKAGE / "fonts" / name
    return path.read_bytes() if FILE.match(name) and path.is_file() else None


def face_css(embed):
    """@font-face rules: the files inline as data URIs (embed) or as /fonts/ links."""
    rules = []
    for family, weight in FACES:
        for subset, unicode_range in RANGES.items():
            name = _name(family, weight, subset)
            data = read(name)
            if data is None:
                continue
            src = "data:font/woff2;base64," + base64.b64encode(data).decode() if embed else f"/fonts/{name}"
            rules.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};font-display:swap;"
                         f"src:url({src}) format('woff2');unicode-range:{unicode_range}}}")
    return "".join(rules)
