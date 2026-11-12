"""The Benchmarks page: one card per task (the change, a row per variant with its median and range, the verdict), a rail."""

import html
import json
from pathlib import Path
from statistics import median

from .... import paths
from ...report.sections.benchmarks import _benchmarks, _runs
from ...report.widgets import _more, _tok, _usd
from ._flat import needs_look, pill

WORSE = 0.05  # a change at least this much costlier goes in "Needs a look"


def _tasks(conn):
    """Per task with at least one variant: {name, about, variants: [(variant, passed, runs, median tokens, median cost,
    fewest tokens, most tokens)]}."""
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
                 median(r[10] or 0 for r in variants[v]), min(r[8] or 0 for r in variants[v]),
                 max(r[8] or 0 for r in variants[v])) for v in order]
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


def _task_card(t, chg, first, last):
    """One card per task: the change in the header, then a row per variant with its median tokens per run as a dot on
    the range of its runs (fewest to most tokens), then each variant's pass count and the verdict."""
    vs = t["variants"]
    lo, hi = min(v[5] for v in vs) * 0.85, max(v[6] for v in vs) * 1.05
    x = (lambda n: (n - lo) / (hi - lo) * 100) if hi > lo else (lambda n: 50)
    rows = "".join(
        f'<div class="armrow"><b>{html.escape(v[0])}</b><div class="ci" title="{_tok(v[5])} to {_tok(v[6])} tokens per run">'
        f'<span class="rng" style="left:{x(v[5]):.1f}%;width:{x(v[6]) - x(v[5]):.1f}%"></span>'
        f'<span class="pt{" s" if i else ""}" style="left:{x(v[3]):.1f}%"></span></div><span class="v">{_tok(v[3])}</span></div>'
        for i, v in enumerate(vs))
    runs = max(v[2] for v in vs) if chg is not None else first[2]
    change = verdict = ""
    if chg is not None:
        change = pill(f"{_pct(chg)} tokens", "ok" if chg < 0 else "bad" if chg >= WORSE else "warn" if chg > 0 else "")
        kept = _kept(first, last)
        verdict = (pill("answer kept" if kept else "answer differs", "ok" if kept else "warn")
                   + f' <span>{first[1]}/{first[2]} then {last[1]}/{last[2]} pass</span>')
    passes = " · ".join(f"{html.escape(v[0])}: pass {v[1]}/{v[2]}" for v in vs)
    about = f'<p class="note">{html.escape(t["about"])}</p>' if t["about"] else ""
    return (f'<section class="card btask"><div class="cardh"><h2 class="mono">{html.escape(t["name"])}</h2>'
            f'<span class="note">{runs} runs each · median tokens per run, range of runs</span>{change}</div>{about}{rows}'
            f'<p class="note bfoot">{passes}{" · " + verdict if verdict else ""}</p></section>')


def page_benchmarks(conn, f):
    head, detail = _benchmarks(conn, paths.tasks())
    sub = '<p class="sub">Run a fixed task before and after a change, and compare tokens.</p>'
    tasks = _tasks(conn)
    if not tasks:
        return (f'<div class="dhead">{sub}</div><div class="dpage"><div class="dcol"><section class="card" id="benchmarks">{head}</section>'
                f'{_more("Benchmark details", "every run and answer", detail)}</div></div>')
    cards, looks = [], []
    for t in tasks:
        chg, first, last = _change(t)
        cards.append(_task_card(t, chg, first, last))
        if chg is None:
            continue
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
    return (f'<div class="dhead">{sub}</div><div class="dpage"><div class="dcol" id="benchmarks">{"".join(cards)}'
            f'{_more("Benchmark details", "every run and answer", detail)}</div>'
            f'<aside class="drail" aria-label="What needs attention">{needs_look(looks)}{cost}</aside></div>')
