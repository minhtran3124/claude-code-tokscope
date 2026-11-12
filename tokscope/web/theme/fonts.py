"""The typefaces of the report and the dashboard: Hanken Grotesk for the interface and numbers;
DM Mono for ids, paths and code. DM Mono has no Vietnamese letters, so IBM Plex Mono covers that range only.

All are SIL Open Font License 1.1. The subsets ship in tokscope/assets/fonts/, so no page asks another
site for a font. Hanken Grotesk is a variable font: one file per subset holds every weight. The report embeds them (one file that works offline and when shared); the dashboard serves them from
/fonts/ with a long cache."""

import base64
import re
from functools import lru_cache

from ... import paths

SANS = "'Hanken Grotesk','Segoe UI',system-ui,sans-serif"
MONO = "'DM Mono','IBM Plex Mono',ui-monospace,Consolas,monospace"

RANGES = {
    "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    "vietnamese": "U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,U+1EA0-1EF9,U+20AB",
}
# (family, weight in the file name, CSS font-weight, subsets on disk)
FACES = [("Hanken Grotesk", "var", "100 900", ("latin", "vietnamese")),
         ("DM Mono", "400", "400", ("latin",)), ("DM Mono", "500", "500", ("latin",)),
         ("IBM Plex Mono", "400", "400", ("vietnamese",)), ("IBM Plex Mono", "500", "500", ("vietnamese",))]
FILE = re.compile(r"^[A-Za-z]+-(\d{3}|var)-[a-z]+\.woff2$")


def _name(family, weight, subset):
    return f"{family.replace(' ', '')}-{weight}-{subset}.woff2"


@lru_cache(maxsize=None)
def read(name):
    """The bytes of a shipped font file, or None when the name is not one of them."""
    path = paths.ASSETS / "fonts" / name
    return path.read_bytes() if FILE.match(name) and path.is_file() else None


def face_css(embed):
    """@font-face rules: the files inline as data URIs (embed) or as /fonts/ links."""
    rules = []
    for family, tag, weight, subsets in FACES:
        for subset in subsets:
            unicode_range = RANGES[subset]
            name = _name(family, tag, subset)
            data = read(name)
            if data is None:
                continue
            src = "data:font/woff2;base64," + base64.b64encode(data).decode() if embed else f"/fonts/{name}"
            rules.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weight};font-display:swap;"
                         f"src:url({src}) format('woff2');unicode-range:{unicode_range}}}")
    return "".join(rules)
