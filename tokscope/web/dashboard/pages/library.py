"""The Library page: the skill list, a skill's files and STE check, and Optimize runs with their benchmark."""

import difflib
import html
import re
import subprocess
import time
from datetime import datetime
from urllib.parse import urlencode

from ....core import markdown, skills
from ....experiments import optimize
from ....features import library
from ...report.sections.skills import _skill_versions
from ...report.widgets import _diff_html, _more, _tok, _usd
from ..common import _dur


def _ste_counts(findings):
    h = library.hard(findings)
    return f'<span class="ste-n" title="STE check: {h} hard findings, {len(findings) - h} hints">STE {h} · {len(findings) - h} hints</span>'


def _skill_card(k, used, lint=None):
    loads, last = used.get(k["dir"], (0, None))
    findings = (lint or {}).get(k["folder"] / "SKILL.md")
    meta = (f"{loads:,} load{'s' * (loads != 1)}" + (f" · last {last[:10]}" if last else "")
            + (f" · {_ste_counts(findings)}" if findings is not None else ""))
    keys = f' data-loads="{loads}" data-ste="{library.hard(findings) if findings is not None else -1}"' 
    badge = f'<span class="badge inst" title="{html.escape(k["reason"])}">installed</span>' if k["origin"] == "installed" else ""
    hide = " hidden" if k["origin"] == "installed" else ""
    return (f'<a class="sk" href="/library?skill={k["id"]}" data-dir="{html.escape(k["dir"])}" data-origin="{k["origin"]}"{keys} '
            f'data-find="{html.escape((k["name"] + " " + k["description"]).lower())}"{hide}>'
            f'<b>{html.escape(k["name"])}{badge}</b><p title="{html.escape(k["description"])}">{markdown.inline(k["description"]) or "<i>No description.</i>"}</p>'
            f'<span class="meta">{meta}</span></a>')


def _library_list(found, used, lint=None, lint_note="", project=""):
    if project and all(k["scope"] == "personal" for k in found):
        lint_note += " This project has no .claude/skills folder; your personal skills load in it."
    if not found:
        return ('<div class="empty"><b>No skills found</b>tokscope looks in ~/.claude/skills and in the .claude/skills '
                'folder of every project a session ran in.</div>')
    installed = sum(k["origin"] == "installed" for k in found)
    tools = ('<div class="tools libtools"><input type="search" id="lib-find" placeholder="Find a skill" aria-label="Find a skill">'
             + (f'<label class="chip"><input type="checkbox" id="lib-inst"> Show installed ({installed})</label>' if installed else "")
             + '<select id="lib-sort" aria-label="Sort skills"><option value="">By name</option><option value="loads">Most loads</option>'
             + ('<option value="ste">Most STE findings</option>' if lint else "") + '</select></div>')
    groups = []
    for scope in dict.fromkeys(k["scope"] for k in found):
        ks = [k for k in found if k["scope"] == scope]
        mine = sum(k["origin"] == "mine" for k in ks)
        title = "Personal · ~/.claude/skills" if scope == "personal" else f"Project · {scope}"
        groups.append(f'<section class="libgroup"><h2 class="sec">{html.escape(title)} <span class="note">{mine} yours'
                      f'{f", {len(ks) - mine} installed" if len(ks) > mine else ""}</span></h2>'
                      f'<div class="libgrid">{"".join(_skill_card(k, used, lint) for k in ks)}</div></section>')
    return (f'<p class="note">Skills you wrote, to read. Installed ones (npx skills, a lock file, an installer) are hidden; '
            f'<code>library.json</code> in the data folder corrects a wrong guess.{lint_note}</p>{tools}{"".join(groups)}'
            '<div class="empty" id="lib-none" hidden><b>No skill matches</b>Try another word.</div>')


def _source(text, pane=""):
    """The file with numbered lines; each line is an anchor (#L12) the STE findings link to."""
    lines = "".join(f'<span class="ln" id="L{i}">{html.escape(line) or " "}</span>' for i, line in enumerate(text.split("\n"), 1))
    return f'<pre class="src"{f" data-pane={pane} hidden" if pane else ""}>{lines}</pre>'


def _marked(line, v):
    """The line with the finding's match marked: the occurrence nearest its column, else the line as it is."""
    m, col = (v.get("match") or "").lower(), max(0, int(v.get("col") or 1) - 1)
    low = line.lower()
    at = low.find(m, max(0, col - len(m))) if m else -1
    at = at if at >= 0 else (low.find(m) if m else -1)
    if at < 0:
        return html.escape(line)
    return f"{html.escape(line[:at])}<mark>{html.escape(line[at:at + len(m)])}</mark>{html.escape(line[at + len(m):])}"


def _ste_pane(findings, text, words, linter, error):
    if error or linter is None:
        why = (f"<b>STE check failed</b>{html.escape(error)}" if error else
               "<b>No STE linter</b>Install the asd-ste100 skill, or set TOKSCOPE_STE_LINT to a ste-lint.py file.")
        return f'<div data-pane="ste" hidden><div class="empty">{why}</div></div>'
    if not findings:
        return '<div data-pane="ste" hidden><div class="empty"><b>No STE findings</b>ste-lint found nothing to change.</div></div>'
    lines, h = text.split("\n"), library.hard(findings)
    rules = {}
    for v in findings:
        rules[v.get("rule", "?")] = rules.get(v.get("rule", "?"), 0) + 1
    items = []
    for v in sorted(findings, key=lambda v: (v.get("line") or 0, v.get("col") or 0)):
        n, hard = v.get("line") or 0, v.get("level") == "advisory-free"
        src = lines[n - 1] if 0 < n <= len(lines) else ""
        items.append(f'<li class="{"hard" if hard else "adv"}"><a class="lnk" href="#L{n}" data-goto="L{n}">L{n}</a>'
                     f'<span class="rule">{html.escape(v.get("rule", "?"))}</span><span class="lvl">{"hard" if hard else "hint"}</span>'
                     f'<code class="line">{_marked(src, v)}</code><span class="msg">{html.escape(v.get("message", ""))}</span></li>')
    by_rule = " · ".join(f"{html.escape(r)} {c}" for r, c in sorted(rules.items(), key=lambda rc: -rc[1]))
    return (f'<div data-pane="ste" hidden><p class="note">{h} hard, {len(findings) - h} hints · '
            f'{len(findings) * 100 / max(words, 1):.1f} per 100 words · {by_rule}. Hints are heuristics (passive voice, tenses): '
            f'read each one. Rules from <code>{html.escape(library._tilde(linter))}</code>.</p>'
            '<label class="chip"><input type="checkbox" id="ste-adv" checked> Show hints</label>'
            f'<ol class="ste">{"".join(items)}</ol></div>')


JOB_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def _optimize_panel(k, found):
    if k["origin"] != "mine":
        return '<p class="note">Installed skills cannot be optimized: the next update of the installer would undo the change.</p>'
    have = optimize.guides_available(found)
    if not have:
        return '<p class="note">To optimize, install one of these skills: ' + ", ".join(optimize.GUIDES) + ".</p>"
    notes = {"optimize-skill": "runs test prompts in subagents, so it costs more",
             "asd-ste100": "STE100 rewrite, checked with ste-lint", "unslop": "removes AI tells from the prose"}
    boxes = "".join(f'<label class="opt"><input type="checkbox" name="guide" value="{g}"{" checked" if g != "optimize-skill" else ""}'
                    f'{"" if g in have else " disabled"}> <b>{g}</b> <span class="note">{notes[g] if g in have else "not installed"}</span></label>'
                    for g in optimize.GUIDES)
    personal = ('<p class="note">This is a personal skill. Test prompts in the job load your personal copy, not the draft, '
                'so optimize-skill cannot test its own cuts.</p>' if k["scope"] == "personal" else "")
    models = "".join(f'<option value="{m}">{m or "default model"}</option>' for m in optimize.MODELS)
    return (f'<form class="optform" id="optimize" data-skill="{k["id"]}">{boxes}{personal}<div class="optrow">'
            f'<select name="model" aria-label="Model">{models}</select>'
            '<label>Spend at most $<input type="number" name="budget" value="2" min="0.5" max="50" step="0.5"></label>'
            '<button type="submit" class="primary">Optimize</button></div>'
            '<p class="note">Runs <code>claude -p</code> on a copy of the skill. The skill changes only when you apply the result.</p>'
            '<p class="err" id="opt-err" hidden></p></form>')


def _jobs_list(k):
    jobs = optimize.jobs_for(k["folder"])
    if not jobs:
        return ""
    rows = "".join(f'<li><a href="/library?skill={k["id"]}&amp;job={j["job"]}"><time data-ts="{html.escape(j["started"])}" data-fmt="dt">{html.escape(j["started"][:16].replace("T", " "))} UTC</time></a> '
                   f'<span class="state {j["state"]}">{j["state"]}</span> {html.escape(", ".join(j["guides"]))}'
                   f'{" · " + _usd(j["cost"]) if j.get("cost") is not None else ""}</li>' for j in jobs[:10])
    return f'<h3 class="sub3">Earlier runs</h3><ul class="plain jobs">{rows}</ul>'


def _measure(folder, rel, linter):
    """(words, ≈tokens, hard STE findings or None) of one Markdown file."""
    path = folder / rel
    if not path.is_file():
        return 0, 0, None
    text = path.read_text(errors="replace")
    hard = None
    if linter:
        try:
            hard = library.hard(library.ste_lint(linter, [path])[path])
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
    return len(markdown.frontmatter(text)[1].split()), len(text) // 4, hard


def _words(a, b):
    """The two lines with the changed words marked, so a one-word edit does not read as a new line."""
    wa, wb = re.split(r"(\s+)", a), re.split(r"(\s+)", b)
    left, right = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        x, y = html.escape("".join(wa[i1:i2])), html.escape("".join(wb[j1:j2]))
        left.append(x if tag == "equal" or not x.strip() else f"<mark>{x}</mark>")
        right.append(y if tag == "equal" or not y.strip() else f"<mark>{y}</mark>")
    join = lambda parts: re.sub(r"</mark>(\s+)<mark>", r"\1", "".join(parts))  # noqa: E731  one mark per changed run
    return join(left), join(right)


def _side_by_side(a, b):
    al, bl = a.splitlines(), b.splitlines()
    rows = []

    def row(i, left, j, right, kind, marked=None):
        lt, rt = marked or (html.escape(left), html.escape(right))
        lc = "del" if kind in ("replace", "delete") and i is not None else "gap" if i is None else ""
        rc = "add" if kind in ("replace", "insert") and j is not None else "gap" if j is None else ""
        rows.append(f'<tr><td class="n">{"" if i is None else i + 1}</td><td class="{lc}">{lt}</td>'
                    f'<td class="n">{"" if j is None else j + 1}</td><td class="{rc}">{rt}</td></tr>')

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, al, bl, autojunk=False).get_opcodes():
        if tag == "equal":
            n = i2 - i1
            for k in (range(n) if n <= 6 else (0, 1, None, n - 2, n - 1)):  # a long unchanged run folds to its ends
                if k is None:
                    rows.append(f'<tr class="fold"><td colspan="4">… {n - 4} unchanged lines</td></tr>')
                else:
                    row(i1 + k, al[i1 + k], j1 + k, bl[j1 + k], "equal")
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            i = i1 + k if i1 + k < i2 else None
            j = j1 + k if j1 + k < j2 else None
            left, right = al[i] if i is not None else "", bl[j] if j is not None else ""
            row(i, left, j, right, tag, _words(left, right) if i is not None and j is not None else None)
    return ('<table class="sbs"><colgroup><col class="n"><col><col class="n"><col></colgroup>'
            '<thead><tr><th></th><th>Before</th><th></th><th>After</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _compare(rel, kind, lines, old_dir, new_dir):
    read = lambda d: (d / rel).read_text(errors="replace") if (d / rel).is_file() else ""  # noqa: E731
    old, new = read(old_dir), read(new_dir)
    tabs = [("sbs", "Side by side"), ("diff", "Diff")] + ([("after", "After"), ("before", "Before")] if rel.endswith(".md") else [])
    seg = "".join(f'<button type="button" class="chip{" on" if i == 0 else ""}" data-cmp="{t}">{label}</button>'
                  for i, (t, label) in enumerate(tabs))
    panes = (f'<div data-cmp-pane="sbs">{_side_by_side(old, new)}</div><div data-cmp-pane="diff" hidden>{_diff_html(lines)}</div>'
             + (f'<div data-cmp-pane="after" class="md" hidden>{markdown.render(markdown.frontmatter(new)[1])}</div>'
                f'<div data-cmp-pane="before" class="md" hidden>{markdown.render(markdown.frontmatter(old)[1])}</div>'
                if rel.endswith(".md") else ""))
    return (f'<section class="card cmp"><div class="viewbar"><h3 class="path">{html.escape(rel)} <span class="note">{kind}</span></h3>'
            f'<span class="seg" role="group" aria-label="Compare">{seg}</span></div>{panes}</section>')


def _bench_section(job, data, conn):
    skill = data["skill"]
    try:
        skills.check_pinnable(skill)
    except ValueError as e:
        return (f'<section class="card" id="bench"><h2 class="sec">Benchmark</h2><p class="note">This skill cannot be benchmarked: '
                f'{html.escape(str(e))}.</p></section>')
    b = optimize.bench_status(job)
    tasks = optimize.bench_tasks(skill)
    body = ""
    if b.get("state") == "running":
        body = ('<p class="runline"><span class="spin"></span>The benchmark is going: '
                f'<b>{b["runs"]}</b> run{"s" * (b["runs"] != 1)} of each version on <code>{html.escape(b["task"])}</code>, '
                f'at most {_usd(b["cap"])} in all.</p><div class="runbar" aria-hidden="true"><i></i></div>'
                f'<pre class="src" id="bench-log">{html.escape(chr(10).join(b["log"])) or "starting…"}</pre>')
    elif b.get("state") in ("done", "failed", "interrupted"):
        res = optimize.bench_results(job, conn.execute("PRAGMA database_list").fetchone()[2])
        trs = "".join(f'<tr><td>{r["label"]} <code>{r["version"][:8]}</code></td><td>{r["passed"]}/{r["runs"]}</td><td>{r["errors"]}</td>'
                      f'<td>{_usd(r["cost"]) if r["cost"] is not None else "–"}</td><td>{_tok(r["tokens"]) if r["tokens"] else "–"}</td>'
                      f'<td>{_dur(r["seconds"]) if r["seconds"] else "–"}</td>'
                      f'<td>{html.escape(", ".join(f"{k} {n}" for k, n in sorted(r["checks"].items())))}</td></tr>' for r in res)
        verdict = ""
        if len(res) == 2 and res[0]["runs"] and res[1]["runs"]:
            cur, new = res
            bits = [f'pass {new["passed"]}/{new["runs"]} vs {cur["passed"]}/{cur["runs"]}']
            for key, word in (("cost", "cost"), ("tokens", "tokens")):
                if cur[key] and new[key]:
                    bits.append(f"{word} {new[key] / cur[key] - 1:+.0%}")
            verdict = (f'<p class="verdict"><b>Draft against current:</b> {", ".join(bits)}. Medians of {cur["runs"]} '
                       f'and {new["runs"]} runs: a small sample, so read it with the diff.</p>')
        state = "" if b["state"] == "done" else f'<p class="err">The benchmark {b["state"]}: {html.escape(b.get("error") or "")}</p>'
        body = (state + verdict + '<table class="bres"><thead><tr><th>Version</th><th>Pass</th><th>Errors</th><th>Median $</th>'
                '<th>Median tokens</th><th>Median time</th><th>Skill check</th></tr></thead>'
                f'<tbody>{trs}</tbody></table><p class="note">Task <code>{html.escape(b["task"])}</code>. '
                'Skill check "ok" means the run read the pinned version.</p>')
    form = ""
    if b.get("state") != "running":
        opts = "".join(f'<option value="{html.escape(n)}" data-cap="{cap}">{html.escape(n)}{" · uses this skill" if uses else ""}</option>'
                       for n, _, cap, uses in tasks)
        runs = "".join(f'<option value="{n}"{" selected" if n == 2 else ""}>{n} per version</option>' for n in optimize.BENCH_RUNS)
        form = ((f'<form class="optrow" id="bench-form"><select name="task" aria-label="Task">{opts}</select>'
                 f'<select name="runs" aria-label="Runs">{runs}</select><button type="submit" class="primary">'
                 f'{"Run the benchmark again" if b.get("state") else "Run the benchmark"}</button>'
                 '<span class="note" id="bench-cap"></span></form>') if tasks else
                '<p class="note">No benchmark task yet. Make one below.</p>')
        form += ('<details class="more" id="task-new"' + ("" if tasks else " open") + '><summary><span class="ttl">Make a task for this skill</span>'
                 '<span class="note">a prompt that uses the skill, and words a good answer has</span></summary>'
                 '<form id="task-form" class="optform">'
                 f'<label class="wide">Prompt <textarea name="prompt" rows="3">/{html.escape(skill)} </textarea></label>'
                 '<label class="wide">Words a good answer has, comma-separated (the grader) <input name="grader" placeholder="CLAUDE_MODEL, ai_config"></label>'
                 '<div class="optrow"><label>Name <input name="name" value="' + html.escape(skill) + '-quick"></label>'
                 '<label>Paths to copy <input name="paths" value="." title="comma-separated; . copies the whole repository"></label>'
                 '<label>$ per run <input type="number" name="budget" value="1.5" min="0.25" max="10" step="0.25"></label></div>'
                 '<p class="note">The task runs in a copy of your repository at HEAD, with the skill version pinned in it. '
                 'Name only the paths the prompt needs: a smaller copy is quicker.</p>'
                 '<p><button type="submit" class="btn">Save the task</button></p></form></details>')
    return (f'<section class="card" id="bench" data-bench="{b.get("state") or ""}"><h2 class="sec">Benchmark</h2>'
            '<p class="note">Run one task on the current skill and on the draft, in fresh headless sessions, and compare pass rate, '
            'cost, tokens and time. It runs claude -p, so it costs money.</p>'
            f'{body}{form}<p class="err" id="bench-err" hidden></p></section>')


def _steps_html(job, started):
    shown, total, _ = optimize.steps(job)
    items = "".join(f'<li class="{st["kind"]}{" sub" if st.get("sub") else ""}"><time>+{_dur(st["t"] - started)}</time>'
                    f'<span>{html.escape(st["text"])}</span></li>' for st in shown)
    more = f'<p class="note">The last {len(shown)} of {total} steps.</p>' if total > len(shown) else ""
    return more + f'<ol class="steps" id="run-list">{items}</ol>'


def _job_view(k, job, linter, conn=None):
    data = optimize.status(job)
    base = f'/library?skill={k["id"]}'
    started = datetime.fromisoformat(data["started"]).timestamp()
    head = (f'<p><a href="{base}">← {html.escape(k["name"])}</a></p><section class="card libhead" id="job" data-job="{job}" '
            f'data-state="{data["state"]}" data-started="{started:.0f}"><h2 class="sec">Optimize run · '
            f'<span class="state {data["state"]}">{data["state"]}</span></h2>'
            f'<dl class="ids"><dt>Started</dt><dd>{html.escape(data["started"].replace("T", " "))}</dd>'
            f'<dt>Guides</dt><dd>{html.escape(", ".join(data["guides"]))}</dd><dt>Model</dt><dd>{html.escape(data["model"] or "default")}</dd>'
            f'<dt>Budget</dt><dd>{_usd(data["budget"])}{" · spent " + _usd(data["cost"]) if data.get("cost") is not None else ""}</dd></dl>')
    if data["state"] == "running":
        _, total, idle = optimize.steps(job)
        files = "".join(f"<li><code>{html.escape(rel)}</code> {kind}</li>" for rel, kind, _ in optimize.changes(job))
        return (head + '<div class="runbar" aria-hidden="true"><i></i></div>'
                f'<p class="runline"><span class="spin" aria-hidden="true"></span>claude -p is working on a copy · '
                f'<b id="run-elapsed">{_dur(time.time() - started)}</b> · <span id="run-count">{total} steps</span></p>'
                f'<p class="warn" id="run-idle"{"" if idle > 120 else " hidden"}>No new step for <span id="run-idle-s">{_dur(idle)}</span>. '
                'A long step (a subagent, a slow answer) can take minutes; if it stays, cancel the run.</p>'
                '<p class="acts"><button type="button" class="btn" data-job-act="cancel">Cancel the run</button></p>'
                '<p class="err" id="opt-err" hidden></p></section>'
                f'<section class="card"><h2 class="sec">Steps</h2>{_steps_html(job, started)}</section>'
                f'<section class="card"><h2 class="sec">Files changed so far</h2><ul class="plain" id="run-files">'
                f'{files or "<li class=note>none yet</li>"}</ul></section>')
    took = _dur(data.get("duration_s"))
    spent = f" · spent {_usd(data['cost'])}" if data.get("cost") is not None else ""
    log = _more("Steps", f"{optimize.steps(job)[1]} steps of the run", _steps_html(job, started), "run-steps")
    if data["state"] in ("failed", "interrupted", "cancelled"):
        word = {"failed": "✕ Failed", "interrupted": "✕ Interrupted", "cancelled": "■ Cancelled"}[data["state"]]
        cls = "off" if data["state"] == "cancelled" else "bad"
        return (head + f'<div class="outcome {cls}"><b>{word} after {took}{spent}</b>'
                f'<span>{html.escape(str(data.get("error") or "")[:1500])}</span></div>'
                '<p class="acts"><button type="button" class="btn" data-job-act="discard">Discard</button></p>'
                '<p class="err" id="opt-err" hidden></p></section>' + log)
    old_dir, new_dir = optimize.compared(job)
    changed = optimize.changes_between(old_dir, new_dir)
    rows, notes = [], []
    for rel, kind, _ in changed:
        if rel.endswith(".md"):
            a, b = _measure(old_dir, rel, linter), _measure(new_dir, rel, linter)
            ste = (f"{a[2] if a[2] is not None else '–'} → {b[2] if b[2] is not None else '–'}") if linter else "–"
            rows.append(f"<tr><td>{html.escape(rel)}</td><td>{kind}</td><td>{a[0]:,} → {b[0]:,}</td>"
                        f"<td>{_tok(a[1])} → {_tok(b[1])}</td><td>{ste}</td></tr>")
            notes.append(f"{rel}: {a[0]:,} → {b[0]:,} words" + (f", STE hard {ste}" if linter else ""))
        else:
            notes.append(f"{rel} {kind}")
    table = ('<table><thead><tr><th>File</th><th>Change</th><th>Words</th><th>≈Tokens</th><th>STE hard</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>') if rows else ""
    decide = ""
    if data["state"] == "applied":
        outcome = (f'<div class="outcome ok"><b>✓ Approved and applied <time data-ts="{html.escape(data["applied"])}" data-fmt="dt">{html.escape(data["applied"][:16].replace("T", " "))} UTC</time></b>'
                   f'<span>Version <code>{data["old_version"]}</code> → <code>{data["new_version"]}</code>. The old version is kept: '
                   'the comparison below and the benchmark still work.</span></div>')
        acts = ""
    elif changed:
        outcome = (f'<div class="outcome ok"><b>✓ Done in {took}{spent} · {len(changed)} file{"s" * (len(changed) != 1)} changed</b>'
                   + "".join(f"<span>{html.escape(n)}</span>" for n in notes)
                   + '<span class="note">Compare the files below, benchmark the draft if you like, then approve or reject it.</span></div>')
        acts = ""
        decide = ('<div class="decide" role="region" aria-label="Decision"><span><b>Keep this draft?</b> '
                  '<span class="note">Approve writes it into the skill; tokscope keeps the old version.</span></span>'
                  '<span class="acts"><a class="btn" href="#bench">Benchmark first</a>'
                  '<button type="button" class="btn danger" data-job-act="discard">Reject</button>'
                  '<button type="button" class="primary" data-job-act="apply">Approve and apply</button></span></div>')
    else:
        outcome = (f'<div class="outcome off"><b>Done in {took}{spent} · nothing changed</b>'
                   '<span>The run left the skill as it was. Its report below says why.</span></div>')
        acts = '<p class="acts"><button type="button" class="btn" data-job-act="discard">Discard</button></p>'
    diffs = "".join(_compare(rel, kind, lines, old_dir, new_dir) for rel, kind, lines in changed)
    bench_html = _bench_section(job, data, conn) if changed and conn is not None else ""
    report = (f'<section class="card"><h2 class="sec">The run\'s report</h2><div class="md">{markdown.render(data["report"])}</div></section>'
              if data.get("report") else "")
    return head + outcome + table + acts + '<p class="err" id="opt-err" hidden></p></section>' + diffs + bench_html + report + log + decide


def _library_skill(k, qs, used, conn, linter=None, found=(), back="/library"):
    listed = library.files(k["folder"])
    names = {rel for rel, _ in listed}
    rel = (qs.get("file") or ["SKILL.md"])[0]
    rel = rel if rel in names else "SKILL.md"
    base = f"/library?skill={k['id']}"
    here = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""

    def link(href):  # a relative link to another file of the skill opens it here
        target = href.split("#")[0]
        parts = []
        for part in (here + target).split("/"):
            if part == "..":
                parts = parts[:-1]
            elif part not in ("", "."):
                parts.append(part)
        target = "/".join(parts)
        return f"{base}&file={target}" if target in names else None

    text, why = library.read(k, rel)
    if text is None:
        view = f'<div class="empty"><b>{html.escape(rel)}</b>{html.escape(why)}</div>'
    elif rel.endswith(".md"):
        meta, body = markdown.frontmatter(text)
        rest = {a: b for a, b in meta.items() if not (rel == "SKILL.md" and a in ("name", "description"))}
        fm = ('<dl class="fm">' + "".join(f"<dt>{html.escape(a)}</dt><dd>{html.escape(b)}</dd>" for a, b in rest.items())
              + "</dl>") if rest else ""
        words = len(body.split())
        findings, error = None, ""
        if linter:
            try:
                findings = library.ste_lint(linter, [k["folder"] / rel])[k["folder"] / rel]
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
                error = str(e)
        ste_tab = (f'<button type="button" class="chip" data-view="ste">STE check'
                   f'{f" <b>{library.hard(findings)}</b>" if findings else ""}</button>')
        view = (f'<div class="viewbar"><span class="note">{words:,} words · ≈{_tok(len(text) // 4)} tokens (characters ÷ 4)</span>'
                '<span class="seg" role="group" aria-label="View"><button type="button" class="chip on" data-view="md">Rendered</button>'
                f'<button type="button" class="chip" data-view="src">Source</button>{ste_tab}</span></div>'
                f'<div class="md" data-pane="md">{fm}{markdown.render(body, link)}</div>'
                f'{_source(text, "src")}{_ste_pane(findings, text, words, linter, error)}')
    else:
        view = f'<div class="viewbar"><span class="note">{text.count(chr(10)) + 1:,} lines</span></div>{_source(text)}'
    tree = "".join(f'<a href="{base}&file={html.escape(r)}"{" class=on aria-current=page" if r == rel else ""}>{html.escape(r)}</a>'
                   for r, _ in listed)
    loads, last = used.get(k["dir"], (0, None))
    tracked = conn.execute("SELECT count(*) FROM skill_versions WHERE skill = ?", (k["dir"],)).fetchone()[0] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone() else 0
    facts = [("Where", f"<code>{html.escape(library._tilde(k['folder']))}</code>"),
             ("Origin", "yours" if k["origin"] == "mine" else f"installed: {html.escape(k['reason'])}"),
             ("Version", f"<code>{skills.fingerprint(k['folder'])}</code>" + (f" · v{html.escape(k['label'])}" if k["label"] else "")),
             ("Loads", f"{loads:,}" + (f", last {last[:10]}" if last else "")
              + (f' · <a href="#v-{html.escape(k["dir"])}">{tracked} tracked versions</a>' if tracked > 1  # only a changed skill has a card
                 else " · 1 tracked version" if tracked else ""))]
    desc = f'<p>{markdown.inline(k["description"])}</p>' if k["description"] else ""
    head = (f'<p><a href="{html.escape(back)}">← All skills</a></p>'
            f'<section class="card libhead"><h2 class="sec">{html.escape(k["name"])}</h2>{desc}'
            '<dl class="ids">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in facts) + "</dl></section>")
    job = (qs.get("job") or [""])[0]
    if JOB_ID.match(job) and (optimize.jobs_dir() / job / "job.json").is_file() and optimize.status(job)["source"] == str(k["folder"]):
        return _job_view(k, job, linter, conn)
    opt = _more("Optimize", "rewrite on a copy with claude -p; apply it if you like the diff",
                _optimize_panel(k, found) + _jobs_list(k), "optimize-panel")
    going = [j for j in optimize.jobs_for(k["folder"]) if j["state"] == "running"]
    if going:  # a run you started and left: one click back to its progress
        opt = (f'<a class="outcome run" href="/library?skill={k["id"]}&amp;job={going[0]["job"]}"><b><span class="spin"></span>'
               f'An optimize run is going</b><span>Started <time data-ts="{html.escape(going[0]["started"])}" data-fmt="hm">{html.escape(going[0]["started"][11:16])} UTC</time> · see its progress</span></a>') + opt
    # a skill with one version and every load tracked has nothing to compare
    versions = (f'<section class="card" id="versions"><h2 class="sec">Versions</h2>{_skill_versions(conn, "full", skill=k["dir"])[1]}</section>'
                if len(skills.versions(conn, k["dir"])) > 1 else "")
    return (f'{head}{opt}<div class="libview"><nav class="card files" aria-label="Files">{tree}</nav>'
            f'<article class="card viewer"><h3 class="path">{html.escape(rel)}</h3>{view}</article></div>{versions}')


def page_library(conn, f, qs, level):
    if level != "full":
        return f'<div class="empty"><b>Skill text is hidden</b>The library shows file contents at the full level only (now {level}).</div>'
    found, used = library.discover(conn, f.project or None), library.usage(conn)
    linter = library.ste_linter(found)
    pick = (qs.get("skill") or [""])[0]
    k = next((k for k in found if k["id"] == pick), None) or next((k for k in library.discover(conn) if k["id"] == pick), None)
    if k:
        return _library_skill(k, qs, used, conn, linter, found, "/library" + (f"?{urlencode({'project': f.project})}" if f.project else ""))
    lint, note = None, " Install the asd-ste100 skill to see STE findings here." if linter is None else ""
    if linter:
        try:
            lint = library.ste_lint(linter, [k["folder"] / "SKILL.md" for k in found])
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            note = f" The STE check failed: {html.escape(str(e))}"
    return _library_list(found, used, lint, note, f.project)
