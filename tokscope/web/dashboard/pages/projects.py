"""The Projects page: projects with their tokens, and a project's MCP servers (add, remove, registry)."""

import html
import re
import time
from pathlib import Path

from ....core.baseline import DEF_METHOD
from ....core.baseline import METHOD as START_METHOD
from ....core.context import METHOD
from ....features import projects
from ...report.widgets import _start_line, _tok, _usd, hue
from ...theme.icons import icon
from .overview import start_detail


def _mcp_of(g):
    return projects.servers(g, (projects.last_health(g["root"]) or (0, None))[1]) if g["root"] else []


def _data(g, mcp, idle):
    base = g.get("base")
    return (f'data-name="{html.escape(g["name"].lower())}" data-find="{html.escape((g["name"] + " " + g["path"]).lower())}" '
            f'data-sessions="{g["sessions"]}" data-tokens="{g["tokens"]}" data-usd="{g["usd"]:.4f}" '
            f'data-last="{html.escape((g["last"] or "")[:19])}" data-start="{base["median"] if base else 0}"')


def _remove_btn(g):
    if not g["root"]:
        return ""
    return (f'<button type="button" class="btn danger" data-proj-remove="{g["id"]}" data-name="{html.escape(g["name"])}" '
            f'aria-label="Remove {html.escape(g["name"])} from tokscope">Remove</button>')


def _pills(mcp):
    pills = "".join(f'<span class="pill">{html.escape(e["name"])}</span> ' for e in mcp[:3])
    return pills + (f'<span class="note">+{len(mcp) - 3}</span>' if len(mcp) > 3 else "")


def _square(name):
    """The project's initials on a coloured square; the colour comes from the name (widgets.hue), as a skill chip's does."""
    letters = "".join(w[0] for w in re.split(r"[-_.\s]+", name) if w)[:2].upper() or "?"
    return f'<span class="psq t{hue(name)}" aria-hidden="true">{html.escape(letters)}</span>'


def _project_row(g, mcp, idle):
    href = f"/projects?p={g['id']}"
    where = f'<div class="note mono">{html.escape(g["path"])}</div>' if g["path"] else ""
    base = g.get("base")
    start = f'<span class="{"up" if idle else ""}">{_tok(base["median"])}</span>' if base else '<span class="note">–</span>'
    return (f'<tr class="prow" {_data(g, mcp, idle)}><td data-label="Project"><div class="pname">{_square(g["name"])}<div>'
            f'<a href="{href}"><b>{html.escape(g["name"])}</b></a>{where}</div></div></td>'
            f'<td data-label="Sessions">{g["sessions"]:,}</td><td data-label="Tokens">{_tok(g["tokens"])}</td>'
            f'<td data-label="API-eq">{_usd(g["usd"])}</td><td data-label="Session start">{start}</td>'
            f'<td class="l" data-label="MCP servers">{_pills(mcp) or "<span class=note>none</span>"}</td>'
            f'<td class="go">{_remove_btn(g)}<a href="{href}" aria-label="Open {html.escape(g["name"])}">›</a></td></tr>')


def _project_card(g, mcp, idle):
    href = f"/projects?p={g['id']}"
    base = g.get("base")
    start = f'<span class="{"up" if idle else ""}">{_tok(base["median"])}</span>' if base else "–"
    last = f' · last {(g["last"] or "")[:10]}' if g["last"] else ""
    return (f'<article class="pcard" {_data(g, mcp, idle)}><div class="pname">{_square(g["name"])}<div>'
            f'<a class="ptitle" href="{href}"><b>{html.escape(g["name"])}</b></a>'
            f'<div class="note mono">{html.escape(g["path"])}</div></div></div>'
            f'<dl class="pstats"><div><dt>Sessions</dt><dd>{g["sessions"]:,}</dd></div><div><dt>Tokens</dt><dd>{_tok(g["tokens"])}</dd></div>'
            f'<div><dt>API-eq</dt><dd>{_usd(g["usd"])}</dd></div><div><dt>Session start</dt><dd>{start}</dd></div></dl>'
            f'<div class="ppills">{_pills(mcp) or "<span class=note>no MCP servers</span>"}</div>'
            f'<div class="pfoot"><span class="note">{last.removeprefix(" · ")}</span><span class="acts">{_remove_btn(g)}'
            f'<a class="btn" href="{href}">Open</a></span></div></article>')


def _projects_rail(found, idle):
    looks = [(g, idle[g["id"]]) for g in found if g["id"] in idle and g.get("base")]
    attn = "".join(f'<li><span class="ai warn">{icon("gauge", 15)}</span><div><a href="/projects?p={g["id"]}">{html.escape(g["name"])} starts at '
                   f'{_tok(g["base"]["median"])}</a><div class="note">{i[0]} unused MCP server{"s" * (i[0] != 1)} add ~{_tok(i[1])} '
                   f'before the first prompt</div></div></li>' for g, i in looks[:3])
    card = (f'<section class="card attention"><h2>Needs a look <span class="pill warn" aria-label="{len(looks[:3])} items">{len(looks[:3])}</span></h2>'
            f'<ol class="plain attn">{attn}</ol></section>' if looks else
            '<section class="card attention"><h2>Needs a look</h2><p class="note">Nothing needs a look.</p></section>')
    starts = sorted((g for g in found if g.get("base")), key=lambda g: -g["base"]["median"])
    if not starts:
        return card
    top = starts[0]["base"]["median"] or 1
    bars = "".join(f'<div class="lim"><div class="l"><span>{html.escape(g["name"])}</span><span>{_tok(g["base"]["median"])}</span></div>'
                   f'<div class="bar"><u style="width:{max(2, round(100 * g["base"]["median"] / top))}%;background:'
                   f'{"var(--fail)" if g["id"] in idle else "var(--mark)"}"></u></div></div>' for g in starts[:6])
    return card + f'<section class="card"><h2>Session start, by project</h2>{bars}</section>'


SORTS = (("tokens", "Most tokens"), ("usd", "Highest API-eq"), ("sessions", "Most sessions"), ("last", "Latest activity"),
         ("start", "Largest session start"), ("name", "Name A–Z"))


def _hidden_panel():
    items = projects.hidden()
    if not items:
        return ""
    rows = "".join(f'<li><code>{html.escape(projects._tilde(_unglob(p)))}</code> '
                   f'<button type="button" class="btn" data-proj-restore="{html.escape(p)}">Restore</button></li>' for p in items)
    return (f'<details class="more" id="proj-hidden"><summary><span class="ttl">Removed from this list ({len(items)})</span>'
            '<span class="note">Restore shows a folder again</span></summary><ul class="plain hlist">' + rows + '</ul></details>')


def _unglob(p):
    return re.sub(r"\[([*?\[])\]", r"\1", p)


def _projects_list(found):
    if not found and not projects.hidden():
        return '<div class="empty"><b>No projects yet</b>Run <code>tokscope ingest</code> after a Claude Code session.</div>'
    real = [g for g in found if g["root"]]
    mcp = {g["id"]: _mcp_of(g) for g in found}
    idle = {g["id"]: x for g in found if (x := projects.idle_cost(g, mcp[g["id"]]))}
    rows = "".join(_project_row(g, mcp[g["id"]], g["id"] in idle) for g in found)
    cards = "".join(_project_card(g, mcp[g["id"]], g["id"] in idle) for g in found)
    tools = ('<div class="tools libtools ptools"><input type="search" id="proj-find" placeholder="Find a project" aria-label="Find a project">'
             '<select id="proj-sort" aria-label="Sort projects">' + "".join(f'<option value="{v}">{t}</option>' for v, t in SORTS) + '</select>'
             f'<span class="seg" role="group" aria-label="View"><button type="button" class="chip on" data-pview="list" aria-pressed="true">{icon("list", 14)}List</button>'
             f'<button type="button" class="chip" data-pview="card" aria-pressed="false">{icon("gallery", 14)}Cards</button></span>'
             '<span class="note" id="proj-count" aria-live="polite"></span></div>'
             '<p class="err" id="proj-err" hidden></p>')
    table = ('<section class="card flat" data-pane="list" id="proj-list"><div class="scroll"><table class="t plist"><thead><tr><th>Project</th><th>Sessions</th>'
             '<th title="All time">Tokens</th><th>API-eq</th><th>Session start</th><th>MCP servers</th><th></th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div></section>'
             f'<div class="pcards" id="proj-cards" hidden>{cards}</div>'
             '<p class="note" id="proj-none" hidden>No project matches. Clear the search.</p>')
    return (f'<p class="sub">{len(real)} projects from your sessions. Worktrees, eval copies and subfolders count with the repository '
            'they belong to; benchmark runs are left out. Remove only takes a project off this list: your sessions\' stored data '
            'and your folders are not deleted.</p>'
            f'<div class="pgrid"><div class="pmain">{tools}{table}{_hidden_panel()}</div><aside class="prail" aria-label="Project start sizes">'
            f'{_projects_rail(found, idle)}</aside></div>')


def _project_view(g):
    checked = projects.last_health(g["root"]) if g["root"] else None
    rows = projects.servers(g, checked[1] if checked else None)
    folders = "".join(f"<li><code>{html.escape(projects._tilde(c))}</code> · {n:,} session{'s' * (n != 1)}"
                      f"{'' if Path(c).exists() else ' · <span class=note>gone</span>'}</li>" for c, n in sorted(g["folders"], key=lambda f: -f[1]))
    keys = sorted(k for k in g["keys"] if k)
    base = g.get("base")
    start = (f'<dt>Session start</dt><dd>{_start_line(base)}</dd>' if base
             else '<dt>Session start</dt><dd class="note">No sessions in this range.</dd>' if "base" in g else "")
    sessions_link = (f' · <a href="/sessions?range=all&amp;project={html.escape(keys[0])}">its sessions</a>' if len(keys) == 1 else "")
    title = (f'<div class="pghead"><p class="crumb"><a href="/projects">Projects</a> / {html.escape(g["name"])}</p>'
             f'<h1>{html.escape(g["name"])}</h1><p class="sub">{g["sessions"]:,} session{"s" * (g["sessions"] != 1)} · '
             f'{_tok(g["tokens"])} tokens</p></div>')
    about = ('<section class="card libhead"><h2>About</h2><dl class="ids">'
             f'<dt>Where</dt><dd><code>{html.escape(g["path"])}</code></dd>'
             f'<dt>Sessions</dt><dd>{g["sessions"]:,}, {(g["first"] or "")[:10]} to {(g["last"] or "")[:10]}{sessions_link}</dd>'
             f'<dt>Tokens</dt><dd>{_tok(g["recent"])} in the last 30 days · {_tok(g["tokens"])} all time · {_usd(g["usd"])} API-eq</dd>{start}</dl>'
             + (f'<details class="folders"><summary>{len(g["folders"])} folders</summary><ul class="plain">{folders}</ul></details>'
                if len(g["folders"]) > 1 else "") + "</section>")
    big = (f'<section class="card pjstart"><h2>Session start</h2><p class="big" title="{html.escape(START_METHOD)}">~{_tok(base["median"])}</p>'
           '<p class="note">Tokens before you type anything: system prompt, tools, MCP servers, skills and CLAUDE.md.</p>'
           f'<p>{start_detail(base)}</p></section>' if base else "")

    def page(main):  # the facts beside the session start, then the MCP cards at full width (the server table is wide)
        return (f'{title}<div class="pjgrid"><div class="pjmain">{about}</div>'
                f'<aside class="pjrail" aria-label="Session start">{big}</aside></div>{main}')

    if g["root"] is None:
        return page("")
    if not g["root"].exists():
        return page('<p class="note">This folder is gone, so its MCP configuration cannot be read.</p>')
    body = []
    for e in rows:
        status = e.get("status") or ("disabled" if e["disabled"] else "")
        cls = ("ok" if status.startswith("✔") else "warn" if status.startswith(("!", "⏸")) else "bad" if status.startswith("✘")
               else "off" if status else "")
        name = html.escape(e["name"]) + (' <span class="badge">shadowed</span>' if e["shadowed"] else "")
        flag = f'<span class="badge flag">{e["flag"]}</span>' if e["flag"] else ""
        secrets = f'<span class="note" title="names only; values are never shown">{html.escape(", ".join(e["secrets"]))}</span>' if e["secrets"] else ""
        if e["source"] in projects.SCOPES:
            act = (f'<button type="button" class="btn" data-mcp-remove="{html.escape(e["name"])}" data-scope="{e["source"]}">Remove</button>')
        elif e["source"].startswith("plugin "):
            act = '<span class="note">with the plugin: /plugin</span>'
        elif e["source"] == "connector":
            act = '<a href="https://claude.ai/customize/connectors" target="_blank" rel="noopener">claude.ai</a>'
        else:
            act = ""
        if status.startswith("! Needs auth") and e.get("toggle", e["name"]):
            status_html = (f'<span class="pill">{html.escape(status)}</span>'
                           f'<code class="login">claude mcp login "{html.escape(e.get("toggle") or e["name"])}"</code>')
        else:
            status_html = f'<span class="pill">{html.escape(status)}</span>' if status else '<span class="note">not checked</span>'
        d = e.get("def_tokens")
        share = (f' · {d / base["median"]:.0%} of start' if d and base and e["flag"] == "never used here" else "")
        defs = (f'<span title="{html.escape(DEF_METHOD)}">~{_tok(d)}{share}</span>' if d else '<span class="note">–</span>')
        p95 = f'~{_tok(e["p95"])}' if e.get("p95") else "–"
        body.append(f'<tr><td data-label="Server">{name} {flag}</td><td data-label="Source">{html.escape(e["source"])}</td>'
                    f'<td data-label="Runs as">{html.escape(e["transport"])} <code>{html.escape(e["target"])}</code> {secrets}</td>'
                    f'<td data-label="Calls">{e["calls"]:,}</td><td data-label="≈Result tokens">{_tok(e["tokens"])}</td>'
                    f'<td data-label="≈p95 result" title="{html.escape(METHOD)}">{p95}</td>'
                    f'<td data-label="≈Definition tokens">{defs}</td>'
                    f'<td data-label="Last session">{(e["last"] or "–")[:10]}</td><td data-label="Status" class="st {cls}">{status_html}</td>'
                    f'<td data-label="Change">{act}</td></tr>')
    when = (f"checked {time.strftime('%H:%M', time.localtime(checked[0]))}" if checked else "not checked yet")
    unused = sum(e["flag"] == "never used here" for e in rows)
    idle = projects.idle_cost(g, rows)
    finding = ""
    if idle:
        n, tokens, usd = idle
        cost = f" (~{_usd(usd)})" if usd is not None else ""
        finding = (f'<p class="finding" title="{html.escape(DEF_METHOD)}"><b>{n} unused MCP server{"s" * (n != 1)} add'
                   f'{"s" * (n == 1)} ~{_tok(tokens)} tokens{cost} to every session start in this project;</b> remove '
                   f'{"them" if n != 1 else "it"}.</p>')
    table = (f'<section class="card" id="mcp" data-project="{g["id"]}"><h2 class="sec">MCP servers</h2>{finding}'
             f'<p class="note">{len(rows)} servers{f", {unused} never used here" if unused else ""}. Calls and result tokens come from '
             'this project\'s transcripts. Precedence: local, project, user, plugin, claude.ai connector; a lower definition with the '
             'same name is shadowed. Plugin servers change with the plugin, connectors at claude.ai.</p>'
             f'<p class="acts"><button type="button" class="btn" id="mcp-check">Check health</button> <span class="note" id="mcp-when">{when}. '
             'The check runs <code>claude mcp list</code> here: it starts the stdio servers and connects to the remote ones.</span></p>'
             '<p class="err" id="opt-err" hidden></p>'
             '<table class="mcp"><thead><tr><th>Server</th><th>Source</th><th>Runs as</th><th>Calls</th><th>≈Result tokens</th>'
             f'<th title="{html.escape(METHOD)}">≈p95 result</th><th title="{html.escape(DEF_METHOD)}">≈Definition tokens</th><th>Last session</th><th>Status</th><th>Change</th></tr></thead><tbody>{"".join(body)}</tbody></table></section>')
    return page(table + _registry_panel() + _mcp_form())


def _registry_panel():
    return ('<details class="more" id="mcp-find"><summary><span class="ttl">Find in the MCP Registry</span>'
            '<span class="note">the official catalog; Use fills in the form below</span></summary>'
            '<form id="reg-form" class="optrow"><input type="search" name="q" placeholder="github, postgres, browser…" aria-label="Search the registry">'
            '<button type="submit" class="btn">Search</button></form>'
            '<p class="note">The search words go to registry.modelcontextprotocol.io. Nothing is installed until you click '
            '<b>Add server</b>; check the package and its author first.</p><p class="err" id="reg-err" hidden></p>'
            '<div class="libgrid" id="reg-results"></div></details>')


def _mcp_form():
    scopes = (("local", "local: only you, in this project (~/.claude.json)"),
              ("project", "project: .mcp.json, shared with the repository"), ("user", "user: you, in every project (~/.claude.json)"))
    return ('<details class="more" id="mcp-add"><summary><span class="ttl">Add a server</span>'
            '<span class="note">runs claude mcp add-json in this project folder</span></summary><form id="mcp-form" class="optform">'
            '<div class="optrow"><label class="namefield">Name <input name="name" required pattern="[A-Za-z0-9_\\-]{1,64}" placeholder="my-server"></label>'
            '<select name="scope" aria-label="Scope">' + "".join(f'<option value="{v}">{t}</option>' for v, t in scopes) + '</select>'
            '<select name="transport" aria-label="Transport"><option value="stdio">stdio (a command)</option>'
            '<option value="http">http (a URL)</option><option value="sse">sse (deprecated)</option></select></div>'
            '<div data-for="stdio"><label class="wide">Command <input name="command" placeholder="npx"></label>'
            '<label class="wide">Arguments, one per line <textarea name="args" rows="3" placeholder="-y&#10;some-mcp-server"></textarea></label></div>'
            '<div data-for="http" hidden><label class="wide">URL <input name="url" placeholder="https://example.com/mcp"></label></div>'
            '<div id="mcp-pairs"></div><p><button type="button" class="btn" id="mcp-pair"></button></p>'
            '<p class="note">In project scope, write a secret as <code>${VAR}</code>: Claude Code reads it from your environment, and the '
            'file you commit holds no secret. tokscope never shows a value again.</p>'
            '<p><button type="submit" class="primary">Add server</button></p><p class="err" id="mcp-err" hidden></p></form></details>')


def page_projects(conn, f, qs, level):
    if level != "full":
        return f'<div class="empty"><b>Projects are hidden</b>This page reads real paths and MCP settings, so it shows at the full level only (now {level}).</div>'
    found = projects.discover(conn)
    projects.add_baselines(conn, found, f.days)
    pick = (qs.get("p") or [""])[0]
    g = next((g for g in found if g["id"] == pick), None)
    return _project_view(g) if g else _projects_list(found)
