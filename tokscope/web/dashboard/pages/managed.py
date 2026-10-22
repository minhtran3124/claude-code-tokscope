"""The Managed page: Claude Managed Agents deployments (pause, unpause), sessions and an agent's configuration."""

import html
import json
from datetime import datetime
from urllib.parse import quote

from ....integrations import managed
from ...report import _table, _tok, _usd
from ..common import _dur


def _when(iso):
    """An API timestamp as local "23 Oct 07:45"; blank or unreadable stays as it is."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d %b %H:%M")
    except (AttributeError, ValueError):
        return iso or "–"


def _id_cell(v):
    return (f"<code>{html.escape(v)}</code>", "raw")


def _dep_status(d):
    """The status, with Pause for an active deployment and Unpause for a paused one; no write for any other state.
    The button shares the status cell, and a manual pause (the usual one) names no reason, so the table still fits.
    Any other reason follows on its own and may wrap, so a long one cannot widen a phone card."""
    reason = (f' <span class="note dep-why">({html.escape(d["paused"].replace("_", " "))})</span>'
              if d["paused"] not in ("", "manual") else "")
    action = {"active": "pause", "paused": "unpause"}.get(d["status"])
    if not action:
        return (html.escape(d["status"]) + reason, "raw")
    return (f'<span class="dep-st">{html.escape(d["status"])} <button type="button" class="btn" data-dep-act="{action}" '
            f'data-dep="{html.escape(d["id"])}" data-name="{html.escape(d["name"] or d["id"])}">{action.capitalize()}</button></span>'
            + reason, "raw")


def _agent_link(a):
    return (f'<a href="/managed?agent={quote(a["id"], safe="")}">{html.escape(a["name"] or a["id"])}</a>', "raw")


def _toolsets(a):
    """One block per toolset: what it is, its default, each tool set apart from that default, and for an MCP toolset
    its server's URL. Blocks, not a table, so a phone needs no sideways scroll."""
    def state(enabled, policy):
        return "off" if enabled is False else policy or "on"
    urls = dict(a["servers"])
    blocks = []
    for t in a["tools"]:
        what = "Built-in tools" if t["type"].startswith("agent_toolset") else "MCP tools" if t["type"] == "mcp_toolset" else t["type"] or "–"
        source = t["server"] or t["name"] or t["type"]
        changed = ", ".join(f"{n}: {state(e, p)}" for n, e, p in t["changed"])
        blocks.append(f'<h3>{html.escape(what)}</h3><dl class="ids"><dt>Source</dt><dd><code>{html.escape(source)}</code></dd>'
                      + (f'<dt>URL</dt><dd><code>{html.escape(urls[t["server"]])}</code></dd>' if urls.get(t["server"]) else "")
                      + f'<dt>Default</dt><dd>{html.escape(state(t["enabled"], t["policy"]))}</dd>'
                      + (f'<dt>Set apart</dt><dd>{html.escape(changed)}</dd>' if changed else "") + "</dl>")
    return blocks


def _agent_view(a, head):
    """One agent's configuration, read only, from the same list read: model, prompt, tools, MCP servers, skills."""
    model = " · ".join(x for x in (a["model"], a["effort"] and f'{a["effort"]} effort', a["speed"]) if x) or "–"
    version = " · ".join(x for x in (a["version"] is not None and f'v{a["version"]}' or "", a["updated_at"] and f'updated {_when(a["updated_at"])}') if x)
    meta = "".join(f"<dt>{html.escape(str(k))}</dt><dd>{html.escape(str(v))}</dd>" for k, v in sorted(a["metadata"].items()))
    tools = _toolsets(a)
    in_tools = {t["server"] for t in a["tools"] if t["server"]}  # a server with no toolset is still listed, with its URL
    servers = "".join(f'<li>{html.escape(n or "–")} <code>{html.escape(u)}</code></li>' for n, u in a["servers"]
                      if not n or n not in in_tools)
    multi = a["multiagent"]
    return "".join([
        '<p><a href="/managed">← All managed agents</a></p>', head,
        f'<section class="card libhead" id="agent-config"><h2 class="sec">{html.escape(a["name"] or a["id"])}</h2><dl class="ids">'
        f'<dt>ID</dt><dd><code>{html.escape(a["id"])}</code></dd>'
        + (f'<dt>Version</dt><dd>{html.escape(version)}</dd>' if version else "")
        + f'<dt>Model</dt><dd>{html.escape(model)}</dd>'
        + (f'<dt>Runs as</dt><dd>{html.escape(a["runs_as"].replace("_", " "))}</dd>' if a["runs_as"] else "")
        + f'<dt>Description</dt><dd>{html.escape(a["description"]) or "<span class=note>none</span>"}</dd>'
        f'<dt>Usage</dt><dd>{a["sessions"]:,} sessions · {_tok(a["tokens"])} · {_usd(a["cost"])}</dd></dl></section>',
        '<section class="card" id="agent-prompt"><h2>System prompt</h2>'
        + (f'<p class="note">{len(a["system"]):,} characters</p><pre class="answer">{html.escape(a["system"])}</pre>'
           if a["system"] else '<p class="note">None.</p>') + '</section>',
        '<section class="card agent-cfg" id="agent-tools"><h2>Tools</h2>'
        + ("".join(tools) or '<p class="note">None.</p>')
        + (f'<h3>MCP servers without tools</h3><ul class="plain">{servers}</ul>' if servers else "") + '</section>',
        '<section class="card agent-cfg" id="agent-more"><h2>Skills and multiagent</h2><dl class="ids">'
        f'<dt>Skills</dt><dd>{html.escape(", ".join(a["skills"])) or "None"}</dd>'
        f'<dt>Multiagent</dt><dd>{"None" if not multi else "<code>" + html.escape(json.dumps(multi)) + "</code>"}</dd>'
        + meta + '</dl></section>',
    ])


def page_managed(qs, level):
    if level != "full":
        return (f'<div class="empty"><b>Managed agents are hidden</b>This page reads your Claude Developer Platform account '
                f'through the ant CLI, so it shows at the full level only (now {level}).</div>')
    data = managed.read()
    pick = (qs.get("agent") or [""])[0]
    read_at = datetime.fromtimestamp(data["read_at"]).strftime("%H:%M:%S")
    refresh = "/managed?refresh=1" + (f"&amp;agent={quote(pick, safe='')}" if pick else "")
    head = (f'<p class="note">Read through <code>ant</code> at {read_at}; kept {managed.CACHE_S:g} s. '
            f'<a href="{refresh}">Refresh</a></p>')
    if "error" in data:
        return (head + '<div class="empty"><b>ant could not read your account</b>Install the ant CLI and sign in with '
                f'<code>ant auth login</code>, then refresh. ant said: {html.escape(data["error"])}</div>')
    deps, sessions, agents = data["deployments"], data["sessions"], data["agents"]
    if pick:
        a = next((a for a in agents if a["id"] == pick), None)
        return _agent_view(a, head) if a else (
            '<p><a href="/managed">← All managed agents</a></p>' + head
            + f'<div class="empty"><b>No such agent</b>No agent <code>{html.escape(pick)}</code> in this workspace.</div>')
    note = f'tokens and cost count the latest {managed.SESSIONS} sessions'
    dep_rows = [(d["name"] or d["id"], _dep_status(d),
                 f'{d["cron"]} {d["tz"]}'.strip() or "–", _when(d["next"]) if d["status"] != "paused" else "–",
                 _usd(d["budget"]), d["sessions"], d["tokens"], _usd(d["cost"]), _id_cell(d["id"])) for d in deps]
    ses_rows = [(s["title"] or s["id"], s["status"], _when(s["created_at"]), _dur(s["active_s"]), s["tokens"],
                 _usd(s["cost"]), _id_cell(s["id"])) for s in sessions]
    agent_rows = [(_agent_link(a), " · ".join(x for x in (a["model"].removeprefix("claude-"), a["effort"]) if x) or "–",
                   ", ".join(a["mcp"]) or "–", ", ".join(a["skills"]) or "–", a["sessions"], a["tokens"], _usd(a["cost"]),
                   _id_cell(a["id"])) for a in agents]
    empty = lambda what: f'<div class="empty"><b>No {what}</b>None in this workspace yet.</div>'  # noqa: E731
    return "".join([
        head,
        f'<section class="card" id="deployments"><h2>Deployments</h2><p class="note">{len(deps)} in this workspace; {note}</p>'
        + (_table(["Deployment", "Status", "Schedule", "Next run", "Budget", "Sessions", "Tokens", "Cost", "ID"], dep_rows, 6)
           if deps else empty("deployments")) + '<p class="err" id="dep-err" role="alert" hidden></p></section>',
        f'<section class="card" id="managed-sessions"><h2>Sessions</h2><p class="note">The latest {len(sessions)}, newest first</p>'
        + (_table(["Session", "Status", "Started", "Active", "Tokens", "Cost", "ID"], ses_rows, 4) if sessions else empty("sessions"))
        + '</section>',
        f'<section class="card" id="agents"><h2>Agents</h2><p class="note">{len(agents)} defined; {note}</p>'
        + (_table(["Agent", "Model", "MCP servers", "Skills", "Sessions", "Tokens", "Cost", "ID"], agent_rows, 5)
           if agents else empty("agents")) + '</section>',
    ])
