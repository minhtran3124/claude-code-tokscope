"""The Library page: the skill list, a skill's files and STE check, its versions and the start form of an optimize run."""

import difflib
import html
import re
import subprocess
from collections import Counter
from urllib.parse import urlencode

from ....core import markdown, skills
from ....features import library
from ...report.sections.skills import _skill_versions
from ...report.widgets import _tok


def _ste_counts(findings):
    h = library.hard(findings)
    return f'<span class="ste-n" title="STE check: {h} hard findings, {len(findings) - h} hints">STE {h} · {len(findings) - h} hints</span>'


VERIFIED = {"verified": ("Verified", "ver ok", "The latest optimize approve of this skill is the version installed now."),
            "edited": ("Edited after run", "ver warn", "An optimize run was approved, and the skill has changed since."),
            "none": ("Not verified", "ver", "No optimize run was approved for this version of the skill.")}


def _ver_badge(state, run=None, link=False):
    label, cls, tip = VERIFIED[state]
    if link and run:
        return f'<a class="badge {cls}" href="/optimize?run={html.escape(run)}" title="{tip}">{label}</a>'
    return f'<span class="badge {cls}" title="{tip}">{label}</span>'


def _verified_map(conn, found):
    """{skill id: (state, run id)}. Skills that share a folder name cannot be told apart in opt_applied, so an approve
    reads as edited only for a name that one folder has."""
    names = Counter(k["dir"] for k in library.discover(conn))   # every project, not the filtered list: opt_applied has no scope
    return {k["id"]: library.verified(conn, k["dir"], k["folder"], names[k["dir"]] == 1) for k in found}


def _skill_card(k, used, lint=None, rng="", state=None, ver=None, top=1):
    loads, last = used.get(k["id"], (0, None))
    findings = (lint or {}).get(k["folder"] / "SKILL.md")
    meta = (f"{loads:,} load{'s' * (loads != 1)}{rng}" + (f" · last {last[:10]}" if last else "")
            + (f" · {_ste_counts(findings)}" if findings is not None else ""))
    st = (state or {}).get(k["id"], "used")
    nbytes, ntok = library.prefix(k)
    meta += f' · <span title="{html.escape(library.PREFIX_METHOD)}">~{ntok:,} tok in every session ({nbytes:,} B)</span>'
    keys = (f' data-loads="{loads}" data-ste="{library.hard(findings) if findings is not None else -1}"'
            f' data-unused="{int(st != "used")}" data-prefix="{ntok}"')
    idle = {"never": ("never used", "No load of this skill in any session the database holds."),
            "unused": (f"unused {library.IDLE_DAYS}+ days", f"Last load more than {library.IDLE_DAYS} days ago, whatever the range.")}.get(st)
    badge = f'<span class="badge flag" title="{idle[1]}">{idle[0]}</span>' if idle else ""
    badge += f'<span class="badge inst" title="{html.escape(k["reason"])}">installed</span>' if k["origin"] == "installed" else ""
    badge += _ver_badge(*(ver or {}).get(k["id"], ("none", None)))
    hide = " hidden" if k["origin"] == "installed" else ""
    bar = (f'<div class="bar-track skbar" title="Description tokens in every session, against the heaviest skill">'
           f'<u style="width:{max(2, ntok * 100 // max(top, 1))}%"></u></div>')
    run = (f'<span class="runopt primary" role="link" tabindex="0" data-go="/library?skill={k["id"]}#optstart-card" '
           'title="Estimate the cost, then start an optimize run of this skill">Run optimize</span>') if _can_run(k) else ""
    return (f'<a class="sk" href="/library?skill={k["id"]}" data-dir="{html.escape(k["dir"])}" data-origin="{k["origin"]}"{keys} '
            f'data-find="{html.escape((k["name"] + " " + k["description"]).lower())}"{hide}>'
            f'<b class="skname">{html.escape(k["name"])}{badge}</b><p title="{html.escape(k["description"])}">{markdown.inline(k["description"]) or "<i>No description.</i>"}</p>'
            f'{bar}<span class="meta">{meta}</span>{run}</a>')


def _library_list(found, used, lint=None, lint_note="", project="", rng="", state=None, ver=None):
    if project and all(k["scope"] == "personal" for k in found):
        lint_note += " This project has no .claude/skills folder; your personal skills load in it."
    if not found:
        return ('<div class="empty"><b>No skills found</b>tokscope looks in ~/.claude/skills and in the .claude/skills '
                'folder of every project a session ran in.</div>')
    installed = sum(k["origin"] == "installed" for k in found)
    tools = ('<div class="tools libtools"><input type="search" id="lib-find" placeholder="Find a skill" aria-label="Find a skill">'
             + (f'<label class="chip"><input type="checkbox" id="lib-inst"> Show installed ({installed})</label>' if installed else "")
             + '<label class="chip"><input type="checkbox" id="lib-dead"> Unused only</label>'
             + '<select id="lib-sort" aria-label="Sort skills"><option value="">By name</option><option value="loads">Most loads</option>'
             + '<option value="unused">Unused first</option><option value="prefix">Heaviest description</option>'
             + ('<option value="ste">Most STE findings</option>' if lint else "") + '</select></div>')
    n_dead, tok_dead = library.dead_cost(found, state or {})
    top = max((library.prefix(k)[1] for k in found), default=1)
    finding = (f'<p class="note finding"><b>{n_dead} skill{"s" * (n_dead != 1)} unused for {library.IDLE_DAYS} days</b> add '
               f'<span title="{html.escape(library.PREFIX_METHOD)}">~{tok_dead:,} tokens</span> to every session.</p>' if n_dead else "")
    groups = []
    for scope in dict.fromkeys(k["scope"] for k in found):
        ks = [k for k in found if k["scope"] == scope]
        mine = sum(k["origin"] == "mine" for k in ks)
        title = "Personal · ~/.claude/skills" if scope == "personal" else f"Project · {scope}"
        groups.append(f'<section class="libgroup"><h2 class="sec">{html.escape(title)} <span class="note">{mine} yours'
                      f'{f", {len(ks) - mine} installed" if len(ks) > mine else ""}</span></h2>'
                      f'<div class="libgrid">{"".join(_skill_card(k, used, lint, rng, state, ver, top) for k in ks)}</div></section>')
    rail = _rail(found, n_dead, tok_dead, top)
    return (f'<div class="libpage"><div class="lib-main"><p class="note">Skills you wrote, to read. Installed ones (npx skills, a lock file, an installer) are hidden; '
            f'<code>library.json</code> in the data folder corrects a wrong guess.{lint_note}</p>{finding}{tools}{"".join(groups)}'
            '<div class="empty" id="lib-none" hidden><b>No skill matches</b>Try another word.</div></div>'
            f'<aside class="lib-rail" aria-label="What needs a look">{rail}</aside></div>')


def _rail(found, n_dead, tok_dead, top):
    """The right rail: what to look at, and the skills' descriptions by weight (the cost every session pays)."""
    mine = sorted((k for k in found if k["origin"] == "mine"), key=lambda k: -library.prefix(k)[1])
    note = (f'<li><span class="k">01</span><div><div>{n_dead} skill{"s" * (n_dead != 1)} unused for {library.IDLE_DAYS} days</div>'
            f'<div class="note">Their descriptions add ~{tok_dead:,} tokens to every session.</div></div></li>' if n_dead else "")
    look = (f'<section class="card"><h2>Needs a look ({1 if n_dead else 0})</h2>'
            + (f'<ol class="attn">{note}</ol>' if note else '<p class="note">No skill stands out.</p>') + '</section>')
    rows = "".join(f'<div class="lim"><div class="l"><span>{html.escape(k["name"])}</span><span>~{library.prefix(k)[1]:,}</span></div>'
                   f'<div class="bar-track"><u style="width:{max(2, library.prefix(k)[1] * 100 // max(top, 1))}%"></u></div></div>'
                   for k in mine[:6])
    cost = (f'<section class="card"><h2>Description cost per session</h2>{rows}</section>' if rows else "")
    return look + cost


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


def _can_run(k):
    return k["origin"] == "mine" and ":" not in k["dir"]


def _start_form(k):
    """Start an evaluated optimize run (the Optimize page): the form asks for the estimate, then for a confirm. While a run of
    the skill is going, a link to it replaces the form."""
    from . import optimize as optpage  # not at the top: the Optimize page imports this module
    if not _can_run(k):
        return ""
    going = optpage.running_for(k["dir"])
    if going:
        return (f'<a class="outcome run" href="/optimize?run={html.escape(going)}"><b><span class="spin"></span>An optimize run of '
                'this skill is going</b><span>See its progress on the Optimize page</span></a>')
    return ('<section class="card" id="optstart-card"><h2 class="sec">Run optimize</h2>'
            '<p class="note">Measures a draft against this skill on its approved eval suite (<code>tokscope optimize suite</code>). '
            'You see the size and the cost first; nothing is spent until you confirm.</p>'
            f'<form class="optform" id="optstart" data-skill="{k["id"]}"><div class="optrow">'
            '<label>Spend at most $<input type="number" name="budget" value="2" min="0.1" step="0.1"></label>'
            '<label>Runs per case <input type="number" name="runs" value="3" min="1" max="10" step="1"></label>'
            '<label>Model <input name="model" value="sonnet" maxlength="64"></label>'
            '<button type="submit" class="primary">Run optimize</button></div>'
            '<div id="opt-est" hidden></div><p class="err" id="optstart-err" hidden></p></form></section>')


def _approvals(conn, k):
    """The versions of this skill an optimize run approved, each linked to its run (below the Versions card, which the
    static report shares and must not link into the dashboard)."""
    approved = library.approved_versions(conn, k["dir"])
    if not approved:
        return ""
    live = skills.fingerprint(k["folder"])
    items = "".join(f'<li><code>{html.escape(v)}</code> · <a href="/optimize?run={html.escape(r)}">{html.escape(r)}</a>'
                    f'{" · installed now" if v == live else ""}</li>' for v, r in reversed(approved.items()))
    return f'<section class="card" id="approvals"><h2 class="sec">Approved by an optimize run</h2><ul class="plain">{items}</ul></section>'


def _library_skill(k, qs, used, conn, linter=None, found=(), back="/library", rng=""):
    from . import optimize as optpage
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
    loads, last = used.get(k["id"], (0, None))
    tracked = conn.execute("SELECT count(*) FROM skill_versions WHERE skill = ?", (k["dir"],)).fetchone()[0] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone() else 0
    facts = [("Where", f"<code>{html.escape(library._tilde(k['folder']))}</code>"),
             ("Origin", "yours" if k["origin"] == "mine" else f"installed: {html.escape(k['reason'])}"),
             ("Version", f"<code>{skills.fingerprint(k['folder'])}</code>" + (f" · v{html.escape(k['label'])}" if k["label"] else "")),
             ("Description", f'<span title="{html.escape(library.PREFIX_METHOD)}">~{library.prefix(k)[1]:,} tokens ({library.prefix(k)[0]:,} B)</span> in every session prefix'),
             ("Loads", f"{loads:,}{rng}" + (f", last {last[:10]}" if last else "")
              + (f' · <a href="#v-{html.escape(k["dir"])}">{tracked} tracked versions</a>' if tracked > 1  # only a changed skill has a card
                 else " · 1 tracked version" if tracked else ""))]
    same = [x for x in library.discover(conn) if x["dir"] == k["dir"]]
    state, run = library.verified(conn, k["dir"], k["folder"], len(same) == 1)
    facts.append(("Optimize", _ver_badge(state, run, link=True)))
    desc = f'<p>{markdown.inline(k["description"])}</p>' if k["description"] else ""
    if _can_run(k) and not optpage.running_for(k["dir"]):
        desc += '<p><a class="primary runbtn" href="#optstart-card">Run optimize</a></p>'
    head = (f'<p><a href="{html.escape(back)}">← All skills</a></p>'
            f'<section class="card libhead"><h2 class="sec">{html.escape(k["name"])}</h2>{desc}'
            '<dl class="ids">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in facts) + "</dl></section>")
    # a skill with one version and every load tracked has nothing to compare
    versions = (f'<section class="card" id="versions"><h2 class="sec">Versions</h2>{_skill_versions(conn, "full", skill=k["dir"])[1]}</section>'
                if len(skills.versions(conn, k["dir"])) > 1 or skills.source_split(conn, k["dir"]) else "")
    return (f'{head}{_start_form(k)}<div class="libview"><nav class="card files" aria-label="Files">{tree}</nav>'
            f'<article class="card viewer"><h3 class="path">{html.escape(rel)}</h3>{view}</article></div>{versions}'
            f'{_approvals(conn, k)}')


def page_library(conn, f, qs, level):
    if level != "full":
        return f'<div class="empty"><b>Skill text is hidden</b>The library shows file contents at the full level only (now {level}).</div>'
    found = library.discover(conn, f.project or None)
    linter = library.ste_linter(found)
    pick = (qs.get("skill") or [""])[0]
    k = next((k for k in found if k["id"] == pick), None) or next((k for k in library.discover(conn) if k["id"] == pick), None)
    used = library.usage(conn, found if k in found else [*found, k] if k else found, f.days, f.project or None, f.now)
    rng = f" in {f.label()}"  # the page has no range select: say which range the counts cover
    if k:
        return _library_skill(k, qs, used, conn, linter, found, "/library" + (f"?{urlencode({'project': f.project})}" if f.project else ""), rng)
    lint, note = None, " Install the asd-ste100 skill to see STE findings here." if linter is None else ""
    if linter:
        try:
            lint = library.ste_lint(linter, [k["folder"] / "SKILL.md" for k in found])
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            note = f" The STE check failed: {html.escape(str(e))}"
    return _library_list(found, used, lint, note, f.project, rng, library.idle(conn, found, f.project or None, f.now),
                         _verified_map(conn, found))
