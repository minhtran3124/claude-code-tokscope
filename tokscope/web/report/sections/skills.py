"""Skill version cards and config change cards."""

import html

from ....core import budgets, errors, skills
from ....features.changes import impact
from ..widgets import _diff_html, _table, _tok, _usd, _vs


FEW_LOADS = 5  # below this many loads a version's median says little
FEW_TAG = ' <span class="few" title="too few loads to judge">few</span>'


def _loads(n):
    return (f"{n}{FEW_TAG if n and n < FEW_LOADS else ''}", "raw")


def _err(calls, failed):
    """`7.5% (3/40)` or a dash with no tool calls."""
    return f"{errors.pct(failed, calls)} ({failed}/{calls})" if calls else "–"


def _skill_versions(conn, level="full", where=None, skill=None):
    """(skills with two or more tracked versions, HTML). A changed skill gets a card: each version's loads and median
    tokens per load, the change from the version before, and the diff between them. A skill with one tracked version
    and loads from before tracking goes in one table that compares the two. Diffs read kept files: full report only.
    `where` (the dashboard's filters) counts only the loads it matches and drops versions with none."""
    by_skill = {}
    for r in skills.versions(conn, skill, where=where):
        if r["loads"] or (r["version"] and not where):
            by_skill.setdefault(r["skill"], []).append(r)
    if not by_skill and where:
        return 0, "<p class='note'>No skill loads match these filters.</p>"
    if not by_skill:
        return 0, ("<p class='note'>No skill versions yet. They are recorded when the mod sees a Skill call and on each "
                   "<code>tokscope ingest</code>.</p>")
    tracked = lambda vs: [v for v in vs if v["version"]]  # noqa: E731
    weight = lambda vs: -sum((v["tokens_median"] or 0) * v["loads"] for v in vs)  # noqa: E731
    changed = {k: vs for k, vs in by_skill.items() if len(tracked(vs)) > 1}
    started = {k: vs for k, vs in by_skill.items() if len(tracked(vs)) == 1 and len(vs) == 2}
    rest = [k for k in by_skill if k not in changed and k not in started]
    single = sorted(k for k in rest if tracked(by_skill[k]))
    unknown = sorted(k for k in rest if not tracked(by_skill[k]))  # loaded, but no folder to hash
    try:
        cfg = budgets.regression_config(budgets.load())
    except budgets.BudgetError:
        cfg = None
    cards = []
    for name, vs in sorted(changed.items(), key=lambda kv: weight(kv[1])):
        rows, prev = [], None
        for v in vs:
            label = f" v{v['label']}" if v["label"] else ""
            rows.append(((f"<code>{html.escape(v['version'] or 'before tracking')}</code>{html.escape(label)}", "raw"),
                         (v["first_seen"] or "")[:10] or "–", _loads(v["loads"]), v["exact"], v["tokens_median"] or 0,
                         _vs(prev, v["tokens_median"]), _err(v["calls"], v["errors"]), v["repeats"], v["interrupts"]))
            prev = v["tokens_median"] if v["tokens_median"] is not None else prev
        diffs = []
        versions = [v["version"] for v in tracked(vs)]
        for old, new in zip(versions, versions[1:]) if level == "full" else []:
            lines = skills.diff(name, old, new)
            if lines is None:
                continue
            added = sum(x.startswith("+") and not x.startswith("+++") for x in lines)
            removed = sum(x.startswith("-") and not x.startswith("---") for x in lines)
            diffs.append(f"<details class='vdiff'><summary>Diff <code>{old}</code> → <code>{new}</code> "
                         f"<span class='note'>{added} added, {removed} removed</span></summary>"
                         f"{_diff_html(lines) if lines else '<p class=note>Same text; only file names changed.</p>'}</details>")
        g = budgets.regression(vs, cfg["pct"], cfg["min_loads"]) if cfg else None
        warn = (f'<p class="note" role="alert"><b>Regression:</b> the newest version costs {g["change_pct"]:+.0f}% per load '
                f'(limit +{cfg["pct"]:g}% with {cfg["min_loads"]}+ loads on both).</p>' if g and g["flagged"] else "")
        cards.append(f'<section class="card" id="v-{html.escape(name)}"><h3>{html.escape(name)}</h3>{warn}'
                     + _table(["version", "first seen", "loads", "exact", "median tokens / load", "vs before", "tool errors",
                                       "repeats", "interrupts"], rows, 4)
                     + "".join(diffs) + "</section>")
    parts = ["<h3>Changed</h3>" + "".join(cards) if cards else
             "<p class='note'>No skill has changed since tracking began. Edit one and its next load shows here, with the diff.</p>"]
    if started:
        rows = []
        # skills loaded since tracking began first: those are the ones with a comparison
        for name, (before, now) in sorted(started.items(), key=lambda kv: (not kv[1][1]["loads"], weight(kv[1]))):
            rows.append((name, _loads(before["loads"]), _tok(before["tokens_median"]) if before["tokens_median"] else "–",
                         (f"<code>{html.escape(now['version'])}</code>", "raw"), (now["first_seen"] or "")[:10],
                         _loads(now["loads"]), now["tokens_median"] or 0, _vs(before["tokens_median"], now["tokens_median"]), _err(before["calls"], before["errors"]),
                         _err(now["calls"], now["errors"])))
        parts.append("<h3>Tracking started</h3><p class='note'>Loads from before tokscope saw the skill against its current "
                     "version. The older loads may span several unknown versions.</p>"
                     + _table(["skill", "loads before", "median before", "version now", "since", "loads", "median tokens / load",
                               "vs before", "errors before", "errors now"], rows, 6))
    if single:
        parts.append(f"<p class='note'>One version, every load tracked: {html.escape(', '.join(single))}.</p>")
    if unknown:
        parts.append(f"<p class='note'>No folder found, so no version (built into Claude Code and not unpacked, or deleted): "
                     f"{html.escape(', '.join(unknown))}.</p>")
    return len(changed), f'<div class="versions">{"".join(parts)}</div>'


def _change_cards(conn, changes):
    if not changes:
        return ('<div class="empty"><b>No changes recorded</b>After editing an agent or skill, run '
                '<code>tokscope change "note" --skill NAME</code> (or <code>--agent TYPE</code>), '
                'and the runs before and after it show here.</div>')
    cards = []
    for change in changes:
        cid, at, note, agent_type, skill = change
        r = impact(conn, change)
        b, a = r["before"], r["after"]
        unit = "subagent run" if agent_type else "skill load"
        if b["n"] and a["n"] and b["tokens_median"]:
            pct = a["tokens_median"] / b["tokens_median"] - 1
            delta = f'<div class="delta">{pct:+.0%}</div><div class="note">median tokens per {unit}</div>'
            if b["errors"]["calls"] and a["errors"]["calls"]:
                delta += (f'<div class="note">tool error rate {errors.pct(b["errors"]["errors"], b["errors"]["calls"])} → '
                          f'{errors.pct(a["errors"]["errors"], a["errors"]["calls"])}</div>')
        else:
            delta = f'<div class="note">Not enough {unit}s on both sides yet.</div>'
        rows = [(side, s["n"], s.get("tokens_median", 0), _tok(s.get("output_median", 0)), (_usd(s.get("usd_median")), "u"),
                 _err(s["errors"]["calls"], s["errors"]["errors"]), s["errors"]["interrupts"],
                 (", ".join(m.removeprefix("claude-") for m in s.get("models", [])), "lm"))
                for side, s in (("before", b), ("after", a))]
        cards.append(
            f'<section class="card" id="change-{cid}"><h3>#{cid} · {html.escape(note)}</h3>'
            f'<p class="note"><time data-ts="{html.escape(at)}" data-fmt="dt">{html.escape(at[:16].replace("T", " "))} UTC</time> · {html.escape(agent_type or skill)} · ±{r["window_days"]} days</p>{delta}'
            + _table(["window", "n", "tokens (median)", "output", "API-eq", "tool errors", "interrupts", "models"], rows, 2) + "</section>")
    return f'<div class="changes">{"".join(cards)}</div>'
