"""The Projects page: projects with their tokens, and a project's MCP servers (add, remove, registry)."""

import html
import secrets
import time
from pathlib import Path

from ....core.baseline import DEF_METHOD
from ....features import projects
from ...report.widgets import _start_line, _tok, _usd
from .overview import start_detail


def _project_card(g):
    mcp = projects.servers(g, (projects.last_health(g["root"]) or (0, None))[1]) if g["root"] else []
    unused = sum(e["flag"] == "never used here" for e in mcp)
    meta = (f"{g['sessions']:,} sessions · last {(g['last'] or '')[:10]}"
            + (f" · {len(g['folders'])} folders" if len(g["folders"]) > 1 else "")
            + (f" · starts ~{_tok(g['base']['median'])}" if g.get("base") else "")
            + (f" · MCP {len(mcp)}" + (f", {unused} never used" if unused else "") if mcp else ""))
    return (f'<a class="sk" href="/projects?p={g["id"]}"><b>{html.escape(g["name"])}</b><p>{html.escape(g["path"])}</p>'
            f'<span class="pnums"><span><b>{_tok(g["recent"])}</b> last 30 days</span><span><b>{_tok(g["tokens"])}</b> all time</span>'
            f'<span><b>{_usd(g["usd"])}</b> API-eq</span></span><span class="meta">{meta}</span></a>')


def _projects_list(found):
    if not found:
        return '<div class="empty"><b>No projects yet</b>Run <code>tokscope ingest</code> after a Claude Code session.</div>'
    real = [g for g in found if g["root"]]
    return (f'<p class="note">{len(real)} projects from your sessions. Worktrees, eval copies and subfolders count with the repository '
            'they belong to; benchmark runs are left out.</p>'
            f'<div class="libgrid">{"".join(_project_card(g) for g in found)}</div>')


def _project_view(g):
    checked = projects.last_health(g["root"]) if g["root"] else None
    rows = projects.servers(g, checked[1] if checked else None)
    folders = "".join(f"<li><code>{html.escape(projects._tilde(c))}</code> · {n:,} session{'s' * (n != 1)}"
                      f"{'' if Path(c).exists() else ' · <span class=note>gone</span>'}</li>" for c, n in sorted(g["folders"], key=lambda f: -f[1]))
    keys = sorted(k for k in g["keys"] if k)
    base = g.get("base")
    start = (f'<dt>Session start</dt><dd>{_start_line(base)}<br>{start_detail(base)}</dd>' if base
             else '<dt>Session start</dt><dd class="note">No sessions in this range.</dd>' if "base" in g else "")
    sessions_link = (f' · <a href="/sessions?range=all&amp;project={html.escape(keys[0])}">its sessions</a>' if len(keys) == 1 else "")
    head = ('<p><a href="/projects">← All projects</a></p>'
            f'<section class="card libhead"><h2 class="sec">{html.escape(g["name"])}</h2><dl class="ids">'
            f'<dt>Where</dt><dd><code>{html.escape(g["path"])}</code></dd>'
            f'<dt>Sessions</dt><dd>{g["sessions"]:,}, {(g["first"] or "")[:10]} to {(g["last"] or "")[:10]}{sessions_link}</dd>'
            f'<dt>Tokens</dt><dd>{_tok(g["recent"])} in the last 30 days · {_tok(g["tokens"])} all time · {_usd(g["usd"])} API-eq</dd>{start}</dl>'
            + (f'<details class="folders"><summary>{len(g["folders"])} folders</summary><ul class="plain">{folders}</ul></details>'
               if len(g["folders"]) > 1 else "") + "</section>")
    if g["root"] is None:
        return head
    if not g["root"].exists():
        return head + '<p class="note">This folder is gone, so its MCP configuration cannot be read.</p>'
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
        body.append(f'<tr><td data-label="Server">{name} {flag}</td><td data-label="Source">{html.escape(e["source"])}</td>'
                    f'<td data-label="Runs as">{html.escape(e["transport"])} <code>{html.escape(e["target"])}</code> {secrets}</td>'
                    f'<td data-label="Calls">{e["calls"]:,}</td><td data-label="≈Result tokens">{_tok(e["tokens"])}</td>'
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
             f'<th title="{html.escape(DEF_METHOD)}">≈Definition tokens</th><th>Last session</th><th>Status</th><th>Change</th></tr></thead><tbody>{"".join(body)}</tbody></table></section>')
    return head + table + _registry_panel() + _mcp_form()


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
