"""SVG and HTML charts for the report's breakdown sections. Colors are CSS tokens (--c1..--c5, --c0 for "Other")
so light and dark mode swap in one place; every chart sits above a table that holds the same numbers."""

import html
from math import ceil, floor, log10

SLOTS = 5  # categorical slots; the rest of the entities fold into "Other"


def tok(v):
    v = v or 0
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v / div:.1f}{unit}"
    return str(int(v))


def _tick(v):
    return tok(v).replace(".0", "")


def _nice(top):
    """The axis end: the first 1, 1.5, 2, 2.5, 3, 4, 5, 6 or 8 x 10^k at or above the largest value, so ticks read as round numbers."""
    if top <= 0:
        return 1
    e = 10 ** floor(log10(top))
    return next(m * e for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * e >= top)


def short(name, n=26):
    """Plugin skills show the part after ':' (as phases.json matches them); long names end in an ellipsis."""
    name = name.rsplit(":", 1)[-1] if ":" in name and not name.startswith("other:") else name
    return name if len(name) <= n else name[:n - 1] + "…"


def _tip(*lines):
    # data-tip is read into innerHTML, so the text is escaped once here and once more as an attribute
    return html.escape("<br>".join(lines))


def fold(items, slots=SLOTS):
    """Top entities by value keep their own slot; the tail sums into one "Other" entry (slot 0)."""
    items = sorted(items, key=lambda kv: -kv[1])
    head, tail = items[:slots], items[slots:]
    out = [(name, v, i + 1) for i, (name, v) in enumerate(head)]
    if tail:
        out.append((f"Other ({len(tail)})", sum(v for _, v in tail), 0))
    return out


def _legend(entries):
    return '<div class="legend">' + "".join(
        f'<span class="key"><i style="background:var(--c{slot})"></i>{html.escape(name)}'
        f'{f" <b>{html.escape(extra)}</b>" if extra else ""}</span>' for name, slot, extra in entries) + "</div>"


def share_bar(items, what):
    """Part-to-whole in one horizontal bar: one segment per entity, 2px surface gaps, the legend carries the shares."""
    parts = fold(items)
    total = sum(v for _, v, _ in parts) or 1
    if not parts:
        return ""
    segs = "".join(
        f'<i style="flex:{v / total:.4f};background:var(--c{slot});--i:{k}" '
        f'data-tip="{_tip(f"<b>{html.escape(name)}</b>", f"{tok(v)} {what}", f"{v / total:.1%} of the total")}"></i>'
        for k, (name, v, slot) in enumerate(parts))
    return (f'<div class="viz"><div class="share" role="img" aria-label="Share of {what} by entity; the table below has every value">'
            f'{segs}</div>{_legend([(n, s, f"{v / total:.0%}") for n, v, s in parts])}</div>')


def _log_axis(lo_v, hi_v):
    lo, hi = floor(log10(max(lo_v, 1))), ceil(log10(max(hi_v, 1)))
    return lo, (hi if hi > lo else lo + 1)


def scatter(points, xlabel, ylabel, labeled=5):
    """How often vs how heavy: log x = count, log y = tokens per use. Top-right holds the frequent, heavy ones."""
    points = [(n, max(x, 1), max(y, 1), t) for n, x, y, t in points if x]
    if len(points) < 2:
        return ""
    w, h, pl, pr, pt, pb = 1100, 280, 56, 140, 14, 34
    xl, xh = _log_axis(min(p[1] for p in points), max(p[1] for p in points))
    yl, yh = _log_axis(min(p[2] for p in points), max(p[2] for p in points))
    X = lambda v: pl + (log10(v) - xl) / (xh - xl) * (w - pl - pr)  # noqa: E731
    Y = lambda v: h - pb - (log10(v) - yl) / (yh - yl) * (h - pt - pb)  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{html.escape(ylabel)} against {html.escape(xlabel)}">']
    for k in range(xl, xh + 1):
        x = X(10 ** k)
        out.append(f'<line class="g" x1="{x:.1f}" x2="{x:.1f}" y1="{pt}" y2="{h - pb}"/>'
                   f'<text x="{x:.1f}" y="{h - pb + 16}" text-anchor="middle">{_tick(10 ** k)}</text>')
    for k in range(yl, yh + 1):
        y = Y(10 ** k)
        out.append(f'<line class="g" x1="{pl}" x2="{w - pr}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text x="{pl - 6}" y="{y + 4:.1f}" text-anchor="end">{_tick(10 ** k)}</text>')
    out.append(f'<text x="{w - pr}" y="{h - 2}" text-anchor="end">{html.escape(xlabel)} →</text>'
               f'<text x="{pl}" y="{pt - 2}" class="ax">↑ {html.escape(ylabel)}</text>')
    top = [p for p in sorted(points, key=lambda p: -p[3])[:labeled]]
    placed, labels = [], []
    for name, x, y, _ in top:  # biggest first, so a crowded spot keeps the label that matters most
        text, cx, cy = short(name, 22), X(x), Y(y)
        tw = 6.4 * len(text)
        fits_right = cx + 9 + tw <= w - 4
        # beside the dot, right then left, then just above it; a label with no free spot is left to the tooltip
        for left, dy in ((not fits_right, 4), (fits_right, 4), (not fits_right, -10)):
            if not left and not fits_right:
                continue
            box = (cx - 9 - tw if left else cx + 9, cy + dy - 11, tw, 13)
            if not any(abs(box[0] - b[0]) < max(box[2], b[2]) and abs(box[1] - b[1]) < 13 for b in placed):
                placed.append(box)
                anchor = ' text-anchor="end"' if left else ""
                labels.append(f'<text class="lbl" x="{cx + (-9 if left else 9):.1f}" y="{cy + dy:.1f}"{anchor}>{html.escape(text)}</text>')
                break
    top = {p[0] for p in top}
    for k, (name, x, y, total) in enumerate(sorted(points, key=lambda p: p[3])):
        cx, cy = X(x), Y(y)
        tip = _tip(f"<b>{html.escape(name)}</b>", f"{x:,} {xlabel}", f"{tok(y)} {ylabel}", f"{tok(total)} in total")
        out.append(f'<g class="pt" data-tip="{tip}" style="--i:{k}"><circle class="hit" cx="{cx:.1f}" cy="{cy:.1f}" r="12"/>'
                   f'<circle class="dot{" hi" if name in top else ""}" cx="{cx:.1f}" cy="{cy:.1f}" r="5"/></g>')
    out += labels
    out.append("</svg>")
    return f'<div class="viz">{"".join(out)}</div>'


def _column(x, y, w, h, r):
    """A column segment with rounded top corners and a square base."""
    r = min(r, h, w / 2)
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + w - r:.1f}"
            f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def weekly_columns(weeks, what):
    """weeks: [(label, {entity: tokens})]. Stacked columns, one per week; an entity keeps its color in every week."""
    if not weeks:
        return ""
    totals = {}
    for _, by in weeks:
        for k, v in by.items():
            totals[k] = totals.get(k, 0) + v
    parts = fold(totals.items())
    slot = {name: s for name, _, s in parts if s}
    order = [name for name, _, s in parts if s] + (["Other"] if any(s == 0 for *_, s in parts) else [])
    h, pl, pt, pb, step = 250, 56, 12, 30, 140
    w = pl + step * len(weeks)
    top = _nice(max(sum(by.values()) for _, by in weeks))
    Y = lambda v: (h - pt - pb) * v / top  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" aria-label="{what} per week by phase">']
    for frac in (0, 0.5, 1):
        y = pt + (h - pt - pb) * (1 - frac)
        out.append(f'<line class="g" x1="{pl}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text x="{pl - 6}" y="{y + 4:.1f}" text-anchor="end">{_tick(top * frac)}</text>')
    cw = 24
    for i, (label, by) in enumerate(weeks):
        x = pl + i * step + (step - cw) / 2
        week_total = sum(by.values()) or 1
        vals = [(n, by.get(n, 0)) for n in order if n != "Other"]
        if "Other" in order:
            vals.append(("Other", sum(v for k, v in by.items() if k not in slot)))
        vals = [(n, v) for n, v in vals if v > 0]
        base = h - pb
        for j, (name, v) in enumerate(vals):
            sh = Y(v)
            seg_h = max(sh - 2, 0.5) if j < len(vals) - 1 else sh  # 2px surface gap above every segment but the top one
            y = base - sh
            color = f"var(--c{slot.get(name, 0)})"
            tip = _tip(f"<b>{html.escape(name)}</b> · week of {html.escape(label)}", f"{tok(v)} {what}", f"{v / week_total:.0%} of that week")
            shape = (f'<path d="{_column(x, y, cw, sh, 4)}"' if j == len(vals) - 1
                     else f'<rect x="{x:.1f}" y="{y + (sh - seg_h):.1f}" width="{cw}" height="{seg_h:.1f}"')
            out.append(f'<g class="seg" data-tip="{tip}" style="--i:{i}">{shape} style="fill:{color}"/>'
                       f'<rect class="hit" x="{x - 10:.1f}" y="{y:.1f}" width="{cw + 20}" height="{sh:.1f}"/></g>')
            base -= sh
        out.append(f'<text x="{x + cw / 2:.1f}" y="{base - 6:.1f}" text-anchor="middle" class="val">{tok(sum(by.values()))}</text>'
                   f'<text x="{x + cw / 2:.1f}" y="{h - 10}" text-anchor="middle">{html.escape(label)}</text>')
    out.append("</svg>")
    legend = _legend([(n, s, "") for n, _, s in parts])
    return f'<div class="viz">{legend}{"".join(out)}</div>'


def ranges(rows, what):
    """rows: [(name, runs, p10, median, p90)]. One line per type from p10 to p90 on a log axis, a dot at the median."""
    if not rows:
        return ""
    w, pl, pr, pt, row_h = 1100, 190, 90, 26, 24
    h = pt + row_h * len(rows) + 8
    xl, xh = _log_axis(min(r[2] for r in rows), max(r[4] for r in rows))
    X = lambda v: pl + (log10(max(v, 1)) - xl) / (xh - xl) * (w - pl - pr)  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{what} per run, by subagent type">']
    for k in range(xl, xh + 1):
        x = X(10 ** k)
        out.append(f'<line class="g" x1="{x:.1f}" x2="{x:.1f}" y1="{pt - 6}" y2="{h - 6}"/>'
                   f'<text x="{x:.1f}" y="{pt - 12}" text-anchor="middle">{_tick(10 ** k)}</text>')
    for i, (name, runs, lo, mid, hi) in enumerate(rows):
        y = pt + row_h * i + row_h / 2
        tip = _tip(f"<b>{html.escape(name)}</b> · {runs} runs", f"median {tok(mid)} {what}", f"p10 {tok(lo)} · p90 {tok(hi)}")
        out.append(f'<g class="rg" data-tip="{tip}" style="--i:{i}"><rect class="hit" x="0" y="{y - row_h / 2:.1f}" width="{w}" height="{row_h}"/>'
                   f'<text x="{pl - 10}" y="{y + 4:.1f}" text-anchor="end" class="name">{html.escape(short(name))}</text>'
                   f'<line class="span" pathLength="1" x1="{X(lo):.1f}" x2="{max(X(hi), X(lo) + 1):.1f}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<circle class="dot hi" cx="{X(mid):.1f}" cy="{y:.1f}" r="5"/>'
                   f'<text x="{X(hi) + 10:.1f}" y="{y + 4:.1f}" class="val">{tok(mid)}</text></g>')
    out.append("</svg>")
    return f'<div class="viz">{"".join(out)}</div>'


def change_text(last, this):
    """Signed change vs last week; a rise past 2x reads as a multiple, which a 2957% would hide."""
    if not last:
        return "new"
    if this >= 2 * last:
        return f"▲ {this / last:.1f}×"
    return f"{'▲' if this >= last else '▼'} {abs(this - last) / last:.0%}"


def dumbbell(rows, what):
    """rows: [(name, last week, this week)]. Last week's dot (light) to this week's dot (full), change at the right."""
    if not rows:
        return ""
    w, pl, pr, pt, row_h = 1100, 220, 90, 26, 26
    h = pt + row_h * len(rows) + 8
    top = _nice(max(max(a, b) for _, a, b in rows))
    X = lambda v: pl + (w - pl - pr) * v / top  # noqa: E731
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{what} last week and this week, by skill">']
    for frac in (0, 0.25, 0.5, 0.75, 1):
        x = X(top * frac)
        out.append(f'<line class="g" x1="{x:.1f}" x2="{x:.1f}" y1="{pt - 6}" y2="{h - 6}"/>'
                   f'<text x="{x:.1f}" y="{pt - 12}" text-anchor="middle">{_tick(top * frac)}</text>')
    for i, (name, last, this) in enumerate(rows):
        y = pt + row_h * i + row_h / 2
        change = change_text(last, this)
        tip = _tip(f"<b>{html.escape(name)}</b>", f"this week {tok(this)}", f"last week {tok(last)}", change)
        out.append(f'<g class="db" data-tip="{tip}" style="--i:{i}"><rect class="hit" x="0" y="{y - row_h / 2:.1f}" width="{w}" height="{row_h}"/>'
                   f'<text x="{pl - 10}" y="{y + 4:.1f}" text-anchor="end" class="name">{i + 1}. {html.escape(short(name))}</text>'
                   + (f'<line class="span" pathLength="1" x1="{X(last):.1f}" x2="{X(this):.1f}" y1="{y:.1f}" y2="{y:.1f}"/>'
                      f'<circle class="dot was" cx="{X(last):.1f}" cy="{y:.1f}" r="5"/>' if last else "")
                   + f'<circle class="dot hi" cx="{X(this):.1f}" cy="{y:.1f}" r="5"/>'
                   f'<text x="{w - 4}" y="{y + 4:.1f}" text-anchor="end" class="val">{change}</text></g>')
    out.append("</svg>")
    legend = ('<div class="legend"><span class="key"><i class="was"></i>last week</span>'
              '<span class="key"><i style="background:var(--c1)"></i>this week</span></div>')
    return f'<div class="viz">{legend}{"".join(out)}</div>'
