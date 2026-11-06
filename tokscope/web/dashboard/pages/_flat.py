"""Markup shared by the pages that follow the console design: a flat table, a status pill and a rail card."""

import html


def pill(text, kind=""):
    return f'<span class="dpill{" " + kind if kind else ""}">{html.escape(str(text))}</span>'


def flat_table(headers, rows, right=()):
    """Cells are pre-escaped HTML. Columns named in `right` align right. data-label names a column when a phone stacks the row."""
    head = "".join(f'<th{" class=r" if h in right else ""}>{html.escape(h)}</th>' for h in headers)
    body = "".join("<tr>" + "".join(
        f'<td data-label="{html.escape(headers[i])}"{" class=r" if headers[i] in right else ""}>{c}</td>'
        for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="ftw"><table class="ft"><tr>{head}</tr>{body}</table></div>'


def card_head(title, note=""):
    return f'<div class="cardh"><h2>{html.escape(title)}</h2>' + (f'<span class="note">{note}</span>' if note else "") + "</div>"


def needs_look(items):
    """The rail's Needs a look card; items are (headline, note) pairs of pre-escaped HTML."""
    if not items:
        return '<section class="card"><h2>Needs a look</h2><p class="note">Nothing needs a look.</p></section>'
    lis = "".join(f'<li><span class="k">{i:02d}</span><div><div>{h}</div><div class="note">{n}</div></div></li>'
                  for i, (h, n) in enumerate(items, 1))
    return f'<section class="card"><h2>Needs a look ({len(items)})</h2><ol class="attn">{lis}</ol></section>'
