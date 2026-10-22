"""Small HTML building blocks: numbers, bars, tables, collapsible sections, the daily chart and diffs."""

import html

from .. import charts


_tok = charts.tok


def _usd(v):
    return "–" if v is None else f"${v:,.2f}"


def _bar(value, top):
    pct = 0 if not top else max(1.5, 100 * (value or 0) / top)
    return f'<span class="bar">{_tok(value)}<i><u style="width:{pct:.1f}%"></u></i></span>'


def _table(headers, rows, bar_col):
    """Cells: plain values, or (text, css class) tuples; class "raw" is pre-escaped HTML. The bar column holds tokens."""
    top = max((r[bar_col] or 0 for r in rows), default=0)
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            # data-label names the column when a phone-width card stacks the table into one block per row
            label = f' data-label="{html.escape(headers[i])}"' if i < len(headers) else ""
            if i == bar_col:
                cells.append(f"<td{label}>{_bar(v, top)}</td>")
            elif isinstance(v, tuple):
                cells.append(f'<td class="{v[1]}"{label}>{v[0] if v[1] == "raw" else html.escape(str(v[0]))}</td>')
            else:
                # a long first-column name wraps on a narrow card; the title repeats it on hover
                title = f' title="{html.escape(str(v))}"' if i == 0 else ""
                cells.append(f"<td{title}{label}>{html.escape(str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def _more(title, note, inner, anchor="", is_open=False):
    """A collapsed section: the summary line is all that shows until it is opened."""
    ident = f' id="{anchor}"' if anchor else ""
    return (f'<details class="more"{ident}{" open" if is_open else ""}><summary><span class="ttl">{title}</span>'
            f'<span class="note">{note}</span></summary>{inner}</details>')


def _pc(x, plain=False):
    """A share as a whole percent; a small non-zero share reads '<1%', not '0%', and a share just under 1 never reads '100%'. plain=True gives text for an attribute."""
    if 0 < x < 0.005:
        return "under 1%" if plain else "&lt;1%"
    return "99%" if 0.995 <= x < 1 else f"{x:.0%}"  # 100% only when it is exactly 100


def _section(title, finding, how, inner, anchor="", pct=None, empty=None):
    """A Breakdowns section: the summary line holds the finding (with a share bar when `pct` is given), and the long
    'how this is counted' text sits inside, above the content. `empty` = (headline, hint) replaces the content."""
    bar = (f'<span class="mini" role="img" aria-label="{_pc(pct, True)}"><i style="width:{min(max(pct, 0), 1) * 100:.1f}%"></i></span>'
           if pct is not None else "")
    body = (f'<div class="empty"><b>{empty[0]}</b>{empty[1]}</div>' if empty else inner)
    return (f'<details class="more finding-sec" id="{anchor}"><summary><span class="ttl">{title}</span>'
            f'<span class="note finding"><b>{finding}</b>{bar}</span></summary>'
            f'<p class="note how">{how}</p>{body}</details>')


def _daily_chart(days, changes):
    if not days:
        return "<p class='note'>No data.</p>"
    w, h, pad_l, pad_b, pad_t = 1100, 230, 56, 22, 18
    top = max(t for _, t, _ in days) or 1
    step = (w - pad_l) / len(days)
    bw = max(2, step - 2)
    index = {d: i for i, (d, _, _) in enumerate(days)}
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Tokens per day">'
                      f'<line class="guide" x1="0" x2="0" y1="{pad_t}" y2="{h - pad_b}"/>']
    for frac in (0, 0.5, 1):
        y = pad_t + (h - pad_t - pad_b) * (1 - frac)
        out.append(f'<line class="g" x1="{pad_l}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end">{_tok(top * frac)}</text>')
    for i, (day, tokens, usd) in enumerate(days):
        x = pad_l + i * step
        bh = (h - pad_t - pad_b) * tokens / top
        tip = html.escape(f"<b>{day}</b><br>{_tok(tokens)} tokens<br><span class='usd'>{_usd(usd)} API-eq</span>")
        out.append(
            f'<g class="d" data-tip="{tip}"><rect class="hit" x="{x:.1f}" y="{pad_t}" width="{step:.1f}" height="{h - pad_t - pad_b}"/>'
            f'<rect class="m" style="--i:{i}" x="{x:.1f}" y="{h - pad_b - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2"/></g>')
        if i % max(1, len(days) // 8) == 0:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{h - 6}" text-anchor="middle">{day[5:]}</text>')
    # 7-day trailing average, so a single heavy day does not read as a trend
    vals = [t for _, t, _ in days]
    pts = []
    for i in range(len(days)):
        window = vals[max(0, i - 6):i + 1]
        avg = sum(window) / len(window)
        pts.append(f"{pad_l + i * step + bw / 2:.1f},{h - pad_b - (h - pad_t - pad_b) * avg / top:.1f}")
    if len(pts) > 1:
        out.append(f'<polyline class="ma" pathLength="1" points="{" ".join(pts)}"/>')
    for cid, at, note, *_ in changes:
        i = index.get(at[:10])
        if i is None:
            continue
        x = pad_l + i * step + bw / 2
        tip = html.escape(f"<b>change #{cid}</b><br>{html.escape(note)}")
        out.append(f'<g data-change="{cid}" data-tip="{tip}" style="cursor:pointer"><line class="chg" x1="{x:.1f}" x2="{x:.1f}" '
                   f'y1="{pad_t - 6}" y2="{h - pad_b}"/><text class="chg-l" x="{x + 4:.1f}" y="{pad_t - 6}">#{cid}</text></g>')
    out.append("</svg>")
    return "".join(out)


def _diff_html(lines):
    cls = lambda l: "add" if l.startswith("+") and not l.startswith("+++") else "del" if l.startswith("-") and not l.startswith("---") \
        else "hunk" if l.startswith(("@@", "+++", "---")) else ""  # noqa: E731
    return "<pre class='diff'>" + "\n".join(f"<span class='{cls(l)}'>{html.escape(l)}</span>" if cls(l) else html.escape(l)
                                            for l in lines) + "</pre>"


def _vs(before, after):
    if not before or after is None:
        return "–"
    pct = after / before - 1
    return f"{'▲' if pct > 0 else '▼'} {abs(pct):.0%}"
