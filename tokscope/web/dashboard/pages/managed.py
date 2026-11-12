"""The Managed page: Claude Managed Agents deployments (pause, unpause), sessions and an agent's configuration."""

import html
import json
from datetime import datetime
from urllib.parse import quote

from ....integrations import managed
from ...report.widgets import _tok, _usd
from ...theme.icons import icon
from ..common import _dur
from ._flat import card_head, flat_table, needs_look, pill


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
        return (f'<div class="empty">{icon("cloud", 34)}<b>Managed agents are hidden</b>This page reads your Claude Developer Platform account '
                f'through the ant CLI, so it shows at the full level only (now {level}).</div>')
    data = managed.read()
    pick = (qs.get("agent") or [""])[0]
    read_at = datetime.fromtimestamp(data["read_at"]).strftime("%H:%M:%S")
    refresh = "/managed?refresh=1" + (f"&amp;agent={quote(pick, safe='')}" if pick else "")
    head = (f'<p class="note">Read through <code>ant</code> at {read_at}; kept {managed.CACHE_S:g} s. '
            f'<a href="{refresh}">Refresh</a></p>')
    if "error" in data:
        return (head + f'<div class="empty">{icon("cloud", 34)}<b>ant could not read your account</b>Install the ant CLI and sign in with '
                f'<code>ant auth login</code>, then refresh. ant said: {html.escape(data["error"])}</div>')
    agents = data["agents"]
    if pick:
        a = next((a for a in agents if a["id"] == pick), None)
        return _agent_view(a, head) if a else (
            '<p><a href="/managed">← All managed agents</a></p>' + head
            + f'<div class="empty"><b>No such agent</b>No agent <code>{html.escape(pick)}</code> in this workspace.</div>')
    return _list_view(data, head)


def _kind(status):
    """A session's status as a pill colour: failed red, in progress yellow, finished green, anything else plain."""
    low = status.lower()
    return "bad" if "fail" in low or "error" in low else "warn" if low in ("running", "rescheduling") else "ok" if low else ""


def _agent_deploy(a, deps):
    """The agent's deployment state as a pill: live when any of its deployments is active, else paused; blank without one."""
    mine = [d["status"] for d in deps if d["agent"] == a["id"]]
    return pill("live", "ok") if "active" in mine else pill(mine[0]) if mine else "–"


def _looks(deps, sessions, names):
    out = [(f'{html.escape(names.get(s["agent"]) or s["agent"] or "A session")} failed at {_when(s["created_at"])[-5:]}',
            html.escape(s["title"] or s["id"])) for s in sessions if _kind(s["status"]) == "bad"][:5]
    out += [(f'{html.escape(d["name"] or d["id"])} paused', html.escape(d["paused"].replace("_", " ")))
            for d in deps if d["status"] == "paused" and d["paused"] not in ("", "manual")]
    return out


def _spend(agents, sessions):
    total = sum(s["cost"] or 0 for s in sessions)
    shares = sorted(((a["cost"], a["name"] or a["id"]) for a in agents if a["cost"]), reverse=True)[:4]
    who = ", ".join(f"{html.escape(n)} {c / total * 100:.0f}%" for c, n in shares) if total else ""
    return (f'<section class="card"><h2>Spend, latest {len(sessions)} sessions</h2><div class="big">{_usd(total)}</div>'
            f'<p class="note">{who + "." if who else "No cost reported."}</p></section>')


def _list_view(data, head):
    deps, sessions, agents = data["deployments"], data["sessions"], data["agents"]
    names = {a["id"]: a["name"] or a["id"] for a in agents}
    empty = lambda what: f'<div class="empty"><b>No {what}</b>None in this workspace yet.</div>'  # noqa: E731
    cut = f'tokens and cost count the latest {managed.SESSIONS} sessions'
    agent_rows = [(_agent_link(a)[0], f'<span class="mono">{html.escape(" · ".join(x for x in (a["model"].removeprefix("claude-"), a["effort"]) if x) or "–")}</span>',
                   str(len(a["tools"])), str(len(a["skills"])), _agent_deploy(a, deps), str(a["sessions"]), _tok(a["tokens"]), _usd(a["cost"]))
                  for a in agents]
    ses_rows = [(f'<span class="mono">{_when(s["created_at"])}</span>',
                 html.escape(names.get(s["agent"]) or s["agent"] or "–") + (f'<div class="note">{html.escape(s["title"])}</div>' if s["title"] else ""),
                 pill(s["status"] or "–", _kind(s["status"])), _dur(s["active_s"]), _tok(s["tokens"]), _usd(s["cost"])) for s in sessions]
    dep_rows = [(f'<span title="{html.escape(d["id"])}">{html.escape(d["name"] or d["id"])}</span>', _dep_status(d)[0],
                 html.escape(f'{d["cron"]} {d["tz"]}'.strip() or "–"), _when(d["next"]) if d["status"] != "paused" else "–",
                 _usd(d["budget"]), str(d["sessions"]), _tok(d["tokens"]), _usd(d["cost"])) for d in deps]
    right = ("Toolsets", "Skills", "Sessions", "Tokens", "Cost", "Active", "Budget")
    cards = [
        f'<section class="card flat" id="agents">{card_head("Agents", f"{len(agents)} defined; {cut}")}'
        + (flat_table(["Agent", "Model", "Toolsets", "Skills", "Deployment", "Sessions", "Tokens", "Cost"], agent_rows, right)
           if agents else empty("agents")) + "</section>",
        f'<section class="card flat" id="managed-sessions">{card_head("Latest sessions", f"{len(sessions)}, newest first")}'
        + (flat_table(["Time", "Agent", "Status", "Active", "Tokens", "Cost"], ses_rows, right) if sessions else empty("sessions")) + "</section>",
        f'<section class="card flat" id="deployments">{card_head("Deployments", f"{len(deps)} in this workspace")}'
        + (flat_table(["Deployment", "Status", "Schedule", "Next run", "Budget", "Sessions", "Tokens", "Cost"], dep_rows, right)
           if deps else empty("deployments")) + '<p class="err" id="dep-err" role="alert" hidden></p></section>',
    ]
    sub = '<p class="sub">Your Claude Managed Agents, their deployments and latest sessions.</p>'
    return (f'<div class="dhead">{sub}{head}</div><div class="dpage"><div class="dcol">{"".join(cards)}</div>'
            f'<aside class="drail" aria-label="What needs attention">{needs_look(_looks(deps, sessions, names))}{_spend(agents, sessions)}</aside></div>')
