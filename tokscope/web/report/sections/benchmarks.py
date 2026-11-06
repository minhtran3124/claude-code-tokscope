"""The Benchmarks section: runs, pass rate, answers with the grader's matches."""

import html
import json
import re
import sqlite3
from pathlib import Path
from statistics import median

from ..common import TOKENS
from ..widgets import _table, _tok, _usd


def _word(text, start, end):
    # widen a match to its whole word, so "retr" shows as "retry" and a match inside another word is visible
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum():
        end += 1
    return start, end


def _highlight(text, patterns):
    """Escape the answer and wrap every grader-pattern match in <mark>."""
    spans = sorted(_word(text, m.start(), m.end()) for p in patterns for m in re.finditer(p, text, re.IGNORECASE))
    out, pos = [], 0
    for start, end in spans:
        if start < pos:
            continue
        out += [html.escape(text[pos:start]), "<mark>", html.escape(text[start:end]), "</mark>"]
        pos = end
    return "".join(out) + html.escape(text[pos:])


def _spread(values, fmt):
    if not values:
        return "–"
    return f"{fmt(median(values))}<span class='usd' style='display:block'>{fmt(min(values))}–{fmt(max(values))}</span>"


def _pass_class(passed, n):
    return "pass" if passed == n else "fail" if passed == 0 else ""


def _runs(conn):
    """Every benchmark run with its tokens and cost; empty when the table does not exist yet."""
    try:
        return conn.execute(
            f"""SELECT b.task, b.variant, b.run_idx, b.passed, b.is_error, b.duration_s, b.result, b.commit_sha,
                       sum({TOKENS}), sum(r.output), sum(r.cost_usd),
                       sum(CASE WHEN r.agent_id IS NULL THEN {TOKENS} END), sum(CASE WHEN r.agent_id IS NOT NULL THEN {TOKENS} END),
                       group_concat(DISTINCT CASE WHEN r.agent_id IS NOT NULL THEN r.model END)
                FROM bench_runs b LEFT JOIN requests r USING (session_id)
                GROUP BY b.run_id ORDER BY b.task, b.variant, b.run_idx""").fetchall()
    except sqlite3.OperationalError:
        return []


def _benchmarks(conn, tasks_dir):
    """Returns (one-line verdict per task, shown up front; the full detail for a collapsed section)."""
    runs = _runs(conn)
    if not runs:
        return "<p class='note'>No benchmark runs yet: <code>tokscope bench run &lt;task&gt; --runs 3</code>.</p>", ""
    tasks = {}
    for r in runs:
        tasks.setdefault(r[0], []).append(r)
    verdicts, cards = [], []
    for name, rows in tasks.items():
        leaky = name.endswith("-leaky")
        spec_path = Path(tasks_dir) / f"{name.removesuffix('-leaky')}.json" if tasks_dir else None
        spec = json.loads(spec_path.read_text()) if spec_path and spec_path.exists() else {}
        variants = {}
        for r in rows:
            variants.setdefault(r[1], []).append(r)
        summary = {v: (sum(r[3] for r in rs), len(rs), median(r[8] or 0 for r in rs), median(r[10] or 0 for r in rs))
                   for v, rs in variants.items()}
        if not leaky:
            parts = [f"<b>{html.escape(v)}</b> <span class='{_pass_class(p, n)}'>{p}/{n}</span> {_tok(t)} tokens "
                     f"<span class='usd'>{_usd(c)}</span>" for v, (p, n, t, c) in summary.items()]
            verdicts.append(f"<tr><td>{html.escape(name)}</td><td class='lm'>{' · '.join(parts)}</td></tr>")
        patterns = spec.get("grader", {}).get("all", [])
        table_rows = []
        for v, rs in variants.items():
            p, n = summary[v][0], summary[v][1]
            models = sorted({m.removeprefix("claude-") for r in rs for m in (r[13] or "").split(",") if m})
            table_rows.append((
                v, (f"<span class='{_pass_class(p, n)}'>{p}/{n}</span>", "raw"), summary[v][2],
                (_spread([r[11] or 0 for r in rs], _tok), "raw"), (_spread([r[12] or 0 for r in rs], _tok), "raw"),
                (_spread([r[9] or 0 for r in rs], _tok), "raw"), (_spread([r[10] or 0 for r in rs], _usd), "raw"),
                (_spread([r[5] or 0 for r in rs], lambda s: f"{s:.0f}s"), "raw"), ", ".join(models)))
        details = "".join(
            f"<details><summary>{html.escape(r[1])} run {r[2]} · "
            f"{'<span class=pass>PASS</span>' if r[3] else '<span class=fail>FAIL</span>'} · {_tok(r[8])} tokens · "
            f"<span class='usd'>{_usd(r[10])}</span> · {r[5]:.0f}s</summary><pre class='answer'>{_highlight(r[6] or '', patterns)}</pre></details>"
            for r in rows)
        warn = "<p class='note'><b>Leaky:</b> the snapshot path named the bug; kept for reference only.</p>" if leaky else ""
        cards.append(
            f'<section class="card{" leaky" if leaky else ""}"><h3>{html.escape(name)}</h3>'
            f'<p class="note">{html.escape(spec.get("about", ""))} Snapshot {(rows[0][7] or "")[:10]}. Highlighted words are grader matches.</p>{warn}'
            + _table(["variant", "pass", "tokens", "main thread", "subagents", "output", "API-eq", "time", "subagent model"], table_rows, 2)
            + f"{details}</section>")
    toggle = ('<label class="note"><input type="checkbox" id="show-leaky"> show leaky runs</label>'
              if any(n.endswith("-leaky") for n in tasks) else "")
    head = f"<table><tr><th>task</th><th style='text-align:left'>variants: pass · median tokens · API-eq</th></tr>{''.join(verdicts)}</table>"
    return head, toggle + "".join(cards)
