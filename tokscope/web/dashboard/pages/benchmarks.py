"""The Benchmarks page: one row per task (before, after, change, verdict), a before and after card per task, a rail."""

import html
import json
from pathlib import Path
from statistics import median

from .... import paths
from ...report.sections.benchmarks import _benchmarks, _runs
from ...report.widgets import _more, _tok, _usd
from ._flat import card_head, flat_table, needs_look, pill

WORSE = 0.05  # a change at least this much costlier goes in "Needs a look"


def _tasks(conn):
    """Per task with at least one variant: {name, about, variants: [(variant, passed, runs, median tokens, median cost)]}."""
    by_task = {}
    for r in _runs(conn):
        by_task.setdefault(r[0], {}).setdefault(r[1], []).append(r)
    out = []
    for name, variants in by_task.items():
        if name.endswith("-leaky"):
            continue  # kept for reference in the details only
        spec_path = Path(paths.tasks()) / f"{name}.json"
        try:
            spec = json.loads(spec_path.read_text()) if spec_path.exists() else {}
        except (OSError, ValueError):
            spec = {}
        order = [v for v in spec.get("variants", {}) if v in variants] + [v for v in variants if v not in spec.get("variants", {})]
        rows = [(v, sum(r[3] or 0 for r in variants[v]), len(variants[v]), median(r[8] or 0 for r in variants[v]),
                 median(r[10] or 0 for r in variants[v])) for v in order]
        out.append({"name": name, "about": spec.get("about", ""), "variants": rows})
    return out


def _change(t):
    """(change as a fraction or None, before row, after row): the first variant against the last."""
    first, last = t["variants"][0], t["variants"][-1]
    if len(t["variants"]) < 2 or not first[3]:
        return None, first, last
    return (last[3] - first[3]) / first[3], first, last


def _pct(x):
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x) * 100:.1f}%"


def _kept(first, last):
    return last[1] / last[2] >= first[1] / first[2]


def page_benchmarks(conn, f):
    head, detail = _benchmarks(conn, paths.tasks())
    sub = '<p class="sub">Run a fixed task before and after a change, and compare tokens.</p>'
    tasks = _tasks(conn)
    if not tasks:
        return (f'<div class="dhead">{sub}</div><div class="dpage"><div class="dcol"><section class="card" id="benchmarks">{head}</section>'
                f'{_more("Benchmark details", "every run and answer", detail)}</div></div>')
    rows, cards, looks = [], [], []
    for t in tasks:
        chg, first, last = _change(t)
        about = f'<div class="note">{html.escape(t["about"])}</div>' if t["about"] else ""
        if chg is None:
            rows.append((f'<b>{html.escape(t["name"])}</b>{about}', str(first[2]), _tok(first[3]), "–", "–", "–"))
            continue
        kept = _kept(first, last)
        runs = max(v[2] for v in t["variants"])
        rows.append((f'<b>{html.escape(t["name"])}</b>{about}', str(runs),
                     f'<span class="mono">{_tok(first[3])}</span><div class="note">{html.escape(first[0])}</div>',
                     f'<span class="mono">{_tok(last[3])}</span><div class="note">{html.escape(last[0])}</div>',
                     f'<span class="{"chg-dn" if chg < 0 else "chg-up" if chg > 0 else "chg-0"}">{_pct(chg)}</span>',
                     pill("answer kept" if kept else "answer differs", "ok" if kept else "warn")
                     + f'<div class="note">{first[1]}/{first[2]} then {last[1]}/{last[2]} pass</div>'))
        top = max(first[3], last[3]) or 1
        bars = "".join(
            f'<div><div class="lab">{html.escape(v[0])}</div><div class="big{" good" if i and chg < 0 else " bad" if i and chg > 0 else ""}">'
            f'{_tok(v[3])}</div><div class="split"><u style="width:{v[3] / top * 100:.0f}%"></u></div></div>'
            for i, v in ((0, first), (1, last)))
        title = f'{t["name"]} · before and after'
        cards.append(f'<section class="card">{card_head(title, f"{runs} runs each, tokens per run")}<div class="bgrid">{bars}</div></section>')
        if chg >= WORSE:
            looks.append((f'{html.escape(t["name"])} got {chg * 100:.0f}% costlier',
                          f'{html.escape(last[0])} uses {_tok(last[3] - first[3])} more tokens per run'))
        elif not _kept(first, last):
            looks.append((f'{html.escape(t["name"])} answers differ',
                          f'{last[1]}/{last[2]} runs pass with {html.escape(last[0])}, {first[1]}/{first[2]} with {html.escape(first[0])}'))
    per_round = [sum(v[4] for v in t["variants"]) for t in tasks]
    cost = ('<section class="card"><h2>Cost of a run</h2>'
            f'<p class="note">One repeat of a task, a run for each variant, costs about {_usd(median(per_round))} at API list prices '
            f'(median over your {len(tasks)} tasks). Start one with <code>tokscope bench run &lt;task&gt; --runs 3</code>.</p></section>')
    table = ('<section class="card flat" id="benchmarks">'
             + flat_table(["Task", "Runs", "Before", "After", "Change", "Verdict"], rows, right=("Runs", "Change")) + "</section>")
    return (f'<div class="dhead">{sub}</div><div class="dpage"><div class="dcol">{table}{"".join(cards)}{_more("Benchmark details", "every run and answer", detail)}</div>'
            f'<aside class="drail" aria-label="What needs attention">{needs_look(looks)}{cost}</aside></div>')
