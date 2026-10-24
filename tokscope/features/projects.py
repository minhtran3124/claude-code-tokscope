"""Your projects, as Claude Code saw them, and the MCP servers each one has: configured where, and used how much.

A project is the folder a session ran in, with its worktrees, eval copies and subfolders folded into the repository
they belong to (a deleted one too, by its name). Temporary folders (/tmp, scratchpads) form one group. The servers come from the files Claude Code
reads: ~/.claude.json (user scope, and local scope per project), the project's .mcp.json, the MCP servers of the
plugins enabled for the project, and the claude.ai connectors the transcripts used. Usage comes from the transcripts.
Nothing here writes a file. Values of env and headers are never read out, only their names.

Approval of .mcp.json servers is not guessed: `claude mcp list` (the health check) reports it.

Adding and removing a server go through `claude mcp add-json` and `claude mcp remove`, run in the project folder with
an explicit scope, so Claude Code writes its own files (~/.claude.json is shared with every running session). A log
in the data folder records each change without its values."""

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .. import paths
from ..core import baseline
from ..core import context
from ..core.calls import CHARS_PER_TOKEN

TOKENS = "(r.input + r.cache_read + r.cache_write_5m + r.cache_write_1h + r.output)"
HEALTH_TIMEOUT = 90
_health = {}


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _tilde(path):
    home, s = str(Path.home()), str(path)
    return "~" + s[len(home):] if s == home or s.startswith(home + "/") else s


def pid(root):
    return hashlib.sha1(str(root).encode()).hexdigest()[:10]


def _tempdir():
    return tempfile.gettempdir()


def _temp(path):
    s, t = str(path), _tempdir()
    return s == t or s.startswith(t + "/") or "/scratchpad" in s


def _hidden_parent(p, known):
    """The folder above the first hidden part of p (.worktrees, .codex-lens-eval-wt-x, .claude/skills/x/eval), when that
    folder is a repository or a known project, or is gone. Hidden folders of the home folder itself stay as they are."""
    home = Path.home()
    for i, part in enumerate(p.parts[1:], 1):
        if part.startswith("."):
            above = Path(*p.parts[:i])
            if above == home or above in home.parents:
                return p
            return above if (above / ".git").exists() or str(above) in known or not above.exists() else p
    return p


def root_of(cwd, known=()):
    """The project a folder belongs to: the git repository around it (a worktree's main one), else a folder
    ~/.claude.json knows, else the folder itself. None for a temporary folder. A worktree or eval copy that is
    deleted still folds into its repository by name: <repo>-worktrees/<x>, <repo>/.<hidden>/..."""
    p = Path(cwd)
    if _temp(p):
        return None
    p = _hidden_parent(p, known)
    home = Path.home()
    chain = [a for a in [p, *p.parents] if a != home and a != a.parent]
    for a in chain:  # <repo>-worktrees/<name> sits beside its repository
        if a.name.endswith("-worktrees") and a.name != "-worktrees":
            return a.parent / a.name.removesuffix("-worktrees")
    for a in chain:
        git = a / ".git"
        if git.is_dir():
            return a
        if git.is_file():  # a linked worktree: "gitdir: <main>/.git/worktrees/<name>"
            m = re.match(r"gitdir:\s*(.+?)/\.git/worktrees/", git.read_text())
            return Path(m.group(1)) if m else a
    return next((a for a in chain if str(a) in known), p)


def _server_entry(name, cfg, source):
    kind = cfg.get("type") or ("stdio" if cfg.get("command") else "http" if cfg.get("url") else "?")
    if cfg.get("command"):
        target = Path(str(cfg["command"])).name + (" " + " ".join(str(a) for a in cfg.get("args", [])[:2]) if cfg.get("args") else "")
        target = re.sub(r"(?i)(token|key|secret|password)=\S+", r"\1=…", target)
    else:
        target = re.sub(r"^\w+://([^/@]*@)?([^/?#]+).*$", r"\2", str(cfg.get("url", "")))  # the host only
    return {"name": name, "source": source, "transport": kind, "target": target,
            "secrets": sorted(set(cfg.get("env", {})) | set(cfg.get("headers", {}))), "key": _key(name)}


def _key(name):
    """The server's part of its tool names: mcp__<key>__tool."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _settings(root):
    """User, project and local settings for root, later ones winning, as Claude Code merges them."""
    merged = {}
    for f in (Path.home() / ".claude" / "settings.json", root / ".claude" / "settings.json", root / ".claude" / "settings.local.json"):
        for k, v in _json(f).items():
            merged[k] = {**merged[k], **v} if isinstance(v, dict) and isinstance(merged.get(k), dict) else v
    return merged


def _plugin_servers(root, settings):
    installed = _json(Path.home() / ".claude" / "plugins" / "installed_plugins.json").get("plugins", {})
    out = []
    for key, on in (settings.get("enabledPlugins") or {}).items():
        if not on:
            continue
        entries = [e for e in installed.get(key, []) if e.get("scope") == "user" or e.get("projectPath") == str(root)]
        if not entries:
            continue
        plugin, folder = key.split("@")[0], Path(entries[0].get("installPath", ""))
        servers = _json(folder / ".mcp.json")
        servers = servers.get("mcpServers", servers)
        inline = _json(folder / ".claude-plugin" / "plugin.json").get("mcpServers")
        if isinstance(inline, str):
            inline = _json(folder / inline)
            inline = inline.get("mcpServers", inline)
        for name, cfg in {**servers, **(inline if isinstance(inline, dict) else {})}.items():
            if isinstance(cfg, dict):
                e = _server_entry(name, cfg, f"plugin {plugin}")
                e["key"], e["toggle"] = f"plugin_{plugin}_{_key(name)}", f"plugin:{plugin}:{name}"
                out.append(e)
    return out


def configured(root, members=()):
    """Every MCP server Claude Code would offer in root, highest precedence first; a lower one with the same name
    is marked as shadowed."""
    cj = _json(Path.home() / ".claude.json")
    proj = cj.get("projects", {})
    local = {}
    for path in [str(root), *map(str, members)]:
        for name, cfg in (proj.get(path, {}).get("mcpServers") or {}).items():
            local.setdefault(name, cfg)
    project_file = _json(root / ".mcp.json")
    project = project_file.get("mcpServers", {}) if isinstance(project_file, dict) else {}
    settings = _settings(root)
    entries = ([_server_entry(n, c, "local") for n, c in local.items()]
               + [_server_entry(n, c, "project") for n, c in project.items()]
               + [_server_entry(n, c, "user") for n, c in (cj.get("mcpServers") or {}).items()]
               + _plugin_servers(root, settings))
    off = set(proj.get(str(root), {}).get("disabledMcpServers") or [])
    off_json = set(settings.get("disabledMcpjsonServers") or []) | set(proj.get(str(root), {}).get("disabledMcpjsonServers") or [])
    seen = set()
    for e in entries:
        e.setdefault("toggle", e["name"])
        e["disabled"] = e["toggle"] in off or (e["source"] == "project" and e["name"] in off_json)
        e["shadowed"] = e["source"] in ("local", "project", "user") and e["name"] in seen
        seen.add(e["name"])
    for name in sorted(off):  # connectors are not in a local file; the /mcp toggle names the ones you turned off
        if name.startswith("claude.ai "):
            entries.append({"name": name.removeprefix("claude.ai "), "source": "connector", "transport": "http", "target": "claude.ai",
                            "secrets": [], "key": "claude_ai_" + _key(name.removeprefix("claude.ai ")), "toggle": name,
                            "disabled": True, "shadowed": False})
    return entries


def _ignored(root, patterns):
    """True when root matches a pattern of "ignore" in projects.json: a path (with ~) or a folder name, * allowed."""
    return root is not None and any(fnmatch.fnmatch(str(root), os.path.expanduser(p)) or fnmatch.fnmatch(root.name, p)
                                    for p in patterns)


def discover(conn, bench_project="%tokscope%-bench-%"):
    """[project] with its folders, sessions, tokens, cost and MCP usage; the temporary folders last, as one group.
    projects.json in the data home may list "ignore" patterns for folders that are not projects."""
    known = set(_json(Path.home() / ".claude.json").get("projects", {}))
    ignore = [str(x) for x in _json(paths.home() / "projects.json").get("ignore", [])]
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400))
    groups = {}
    for cwd, keys, sessions, tokens, recent, usd, first, last in conn.execute(
            f"SELECT s.cwd, group_concat(DISTINCT s.project), count(DISTINCT s.session_id), sum({TOKENS}), "
            f"sum(CASE WHEN r.ts >= ? THEN {TOKENS} ELSE 0 END), sum(r.cost_usd), min(r.ts), max(r.ts) "
            f"FROM sessions s JOIN requests r USING (session_id) WHERE s.project NOT LIKE ? AND s.cwd IS NOT NULL "
            f"GROUP BY s.cwd", (since, bench_project)):
        root = root_of(cwd, known)
        if _ignored(root, ignore):
            continue
        g = groups.setdefault(str(root) if root else "", {
            "id": pid(root) if root else "temp", "root": root, "name": root.name if root else "Temporary folders",
            "path": _tilde(root) if root else _tempdir(), "folders": [], "keys": set(), "sessions": 0, "tokens": 0,
            "recent": 0, "usd": 0.0, "first": first, "last": last, "mcp": {}, "defs": {}})
        g["folders"].append((cwd, sessions))
        g["keys"].update((keys or "").split(","))
        g["sessions"] += sessions
        g["tokens"] += tokens or 0
        g["recent"] += recent or 0
        g["usd"] += usd or 0
        g["first"], g["last"] = min(g["first"] or first, first or g["first"]), max(g["last"] or "", last or "")
    by_cwd = {cwd: g for g in groups.values() for cwd, _ in g["folders"]}
    for cwd, name, calls, chars, last in conn.execute(
            "SELECT s.cwd, t.name, count(*), sum(t.result_chars), max(s.last_ts) FROM tool_calls t JOIN sessions s USING (session_id) "
            "WHERE t.name LIKE 'mcp__%' AND s.project NOT LIKE ? GROUP BY s.cwd, t.name", (bench_project,)):
        if cwd not in by_cwd or name.count("__") < 2:
            continue
        u = by_cwd[cwd]["mcp"].setdefault(name.split("__")[1], {"calls": 0, "tokens": 0, "last": ""})
        u["calls"] += calls
        u["tokens"] += round((chars or 0) / CHARS_PER_TOKEN)
        u["last"] = max(u["last"], last or "")
    for (cwd, server), p95 in context.server_p95(conn, bench_project).items():
        if cwd in by_cwd and server in by_cwd[cwd]["mcp"]:
            by_cwd[cwd]["mcp"][server]["p95"] = p95
    for cwd, server, tools, chars in conn.execute(  # oldest first, so a server's newest definition wins
            "SELECT s.cwd, d.server, d.tools, d.chars FROM mcp_defs d JOIN sessions s USING (session_id) "
            "WHERE s.project NOT LIKE ? ORDER BY s.last_ts", (bench_project,)):
        if cwd in by_cwd:
            by_cwd[cwd]["defs"][server] = (tools, chars)
    out = sorted((g for k, g in groups.items() if k), key=lambda g: -g["tokens"])
    return out + [groups[""]] if "" in groups else out


def add_baselines(conn, found, days=None, now=None, bench_project="%tokscope%-bench-%"):
    """Set g["base"] on each project of `found`: the baseline stats (core.baseline.stats) of the sessions whose first
    request falls in the last `days` days (None: all time), or None without any."""
    rows = baseline.starts(conn, "WHERE s.project NOT LIKE ?", (bench_project,))
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime((now or time.time()) - days * 86400)) if days else ""
    for g in found:
        cwds = {c for c, _ in g["folders"]}
        mine = [r for r in rows if r[1] in cwds]
        g["base"] = baseline.stats([r for r in mine if (r[2] or "") >= since], None, mine)


def idle_cost(g, rows):
    """(servers, tokens, usd) the project's never-used servers add to every session start; None when no unused server
    has a measured definition. usd is None without a baseline model to price it."""
    unused = [e for e in rows if e["flag"] == "never used here" and e.get("def_tokens")]
    if not unused:
        return None
    tokens = sum(e["def_tokens"] for e in unused)
    base = g.get("base")
    usd = baseline.start_usd(base["model"], base["median"]) if base else None  # priced at a typical start, not at 1M tokens
    return len(unused), tokens, None if usd is None else tokens * usd / base["median"]


def _health_key(name):
    """The tool-name key of a server as `claude mcp list` names it."""
    if name.startswith("claude.ai "):
        return "claude_ai_" + _key(name.removeprefix("claude.ai "))
    if name.startswith("plugin:") and name.count(":") >= 2:
        _, plugin, server = name.split(":", 2)
        return f"plugin_{plugin}_{_key(server)}"
    return _key(name)


def servers(g, status=None):
    """The project's servers: the configured ones with their use; then the ones only the health check or the
    transcripts know (claude.ai connectors, or a server removed since). `status` is the health check's answer."""
    if g["root"] is None:
        return []
    rows = configured(g["root"], [Path(c) for c, _ in g["folders"]])
    for name in status or {}:
        if _health_key(name) not in {e["key"] for e in rows}:
            source = "connector" if name.startswith("claude.ai ") else "plugin " + name.split(":")[1] if name.startswith("plugin:") else "configured"
            rows.append({"name": name.removeprefix("claude.ai ") if source == "connector" else name.split(":")[-1],
                         "source": source, "transport": "http" if source == "connector" else "?",
                         "target": "claude.ai" if source == "connector" else "", "secrets": [], "key": _health_key(name),
                         "toggle": name, "disabled": False, "shadowed": False})
    for key in g["mcp"]:
        if key not in {e["key"] for e in rows}:
            connector = key.startswith("claude_ai_")
            rows.append({"name": key.removeprefix("claude_ai_") if connector else key,
                         "source": "connector" if connector else "not configured now", "transport": "http" if connector else "?",
                         "target": "claude.ai" if connector else "", "secrets": [], "key": key, "toggle": "", "disabled": False,
                         "shadowed": False})
    by_key = {_health_key(n): v for n, v in (status or {}).items()}
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400))
    for e in rows:
        u = g["mcp"].get(e["key"], {}) if not e["shadowed"] else {}
        d = g.get("defs", {}).get(e["key"]) if not e["shadowed"] else None
        e.update(calls=u.get("calls", 0), tokens=u.get("tokens", 0), p95=u.get("p95"), last=u.get("last", ""),
                 def_tokens=round(d[1] / CHARS_PER_TOKEN) if d else None,
                 status=None if e["shadowed"] else by_key.get(e["key"]))
        off = e["disabled"] or (e["status"] or "").startswith(("⊘", "✘ Rejected"))
        e["flag"] = ("" if off or e["shadowed"] else "never used here" if not e["calls"]
                     else "idle 30+ days" if e["last"] < since else "")
    order = {"local": 0, "project": 1, "user": 2}
    return sorted(rows, key=lambda e: (e["shadowed"], -e["calls"], order.get(e["source"], 3), e["name"].lower()))


def health(root, claude):
    """{server name: status} from `claude mcp list` run in root; the command and URL part of each line is dropped,
    since it can carry a credential. Cached for the dashboard until the next check."""
    run = subprocess.run([claude, "mcp", "list"], cwd=root, capture_output=True, text=True, timeout=HEALTH_TIMEOUT)
    status = {}
    for line in run.stdout.splitlines():
        m = re.match(r"^(.+?): .* - (.+)$", line.strip())
        if m:
            status[m.group(1).strip()] = m.group(2).strip()
    if run.returncode != 0 and not status:
        raise RuntimeError((run.stderr or run.stdout).strip()[-300:] or f"claude mcp list exited {run.returncode}")
    _health[str(root)] = (time.time(), status)
    return status


def last_health(root):
    return _health.get(str(root))


NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HEADER = re.compile(r"^[A-Za-z0-9-]{1,64}$")
SCOPES = ("local", "project", "user")
TRANSPORTS = ("stdio", "http", "sse")
CLI_TIMEOUT = 60


def build(form):
    """(name, scope, config) from the dashboard's form, or ValueError with what is wrong."""
    name, scope, kind = str(form.get("name", "")).strip(), form.get("scope"), form.get("transport")
    if not NAME.match(name):
        raise ValueError("the name may have letters, digits, - and _ only (at most 64)")
    if scope not in SCOPES:
        raise ValueError("the scope must be local, project or user")
    if kind not in TRANSPORTS:
        raise ValueError("the transport must be stdio, http or sse")
    pairs = {}
    for row in form.get("pairs") or []:
        key, value = str(row.get("key", "")).strip(), str(row.get("value", ""))
        if not key:
            continue
        if not (re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key) if kind == "stdio" else HEADER.match(key)):
            raise ValueError(f"{'variable' if kind == 'stdio' else 'header'} name {key!r} is not valid")
        if "\n" in value or "\r" in value:
            raise ValueError(f"the value of {key} has a line break")
        pairs[key] = value
    if kind == "stdio":
        command = str(form.get("command", "")).strip()
        if not command or "\n" in command:
            raise ValueError("a stdio server needs one command line")
        args = [a for a in (str(x) for x in form.get("args") or []) if a.strip()]
        cfg = {"type": "stdio", "command": command, "args": args, **({"env": pairs} if pairs else {})}
    else:
        url = str(form.get("url", "")).strip()
        if not re.match(r"^https?://[^\s]+$", url):
            raise ValueError("the URL must start with http:// or https://")
        cfg = {"type": kind, "url": url, **({"headers": pairs} if pairs else {})}
    return name, scope, cfg


def _log(root, action, name, scope, ok):
    path = paths.home() / "data" / "mcp-changes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:  # names and scopes only: a value can be a credential
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "project": str(root), "action": action,
                            "name": name, "scope": scope, "ok": ok}) + "\n")


def _cli(root, claude, args, secrets=()):
    run = subprocess.run([claude, "mcp", *args], cwd=root, capture_output=True, text=True, timeout=CLI_TIMEOUT)
    out = (run.stdout + run.stderr).strip()
    for s in secrets:  # never send a value back, even inside an error message
        if s and len(s) > 3:
            out = out.replace(s, "…")
    _health.pop(str(root), None)  # the list changed: the last check is out of date
    return run.returncode == 0, out[-600:]


def add(root, form, claude):
    name, scope, cfg = build(form)
    secrets = list((cfg.get("env") or cfg.get("headers") or {}).values())
    ok, out = _cli(root, claude, ["add-json", "-s", scope, name, json.dumps(cfg)], secrets)
    _log(root, "add", name, scope, ok)
    if not ok:
        raise RuntimeError(out or "claude mcp add-json failed")
    return name, scope


def remove(root, name, scope, claude):
    if not NAME.match(str(name)) or scope not in SCOPES:
        raise ValueError("pick a server of local, project or user scope")
    ok, out = _cli(root, claude, ["remove", "-s", scope, name])
    _log(root, "remove", name, scope, ok)
    if not ok:
        raise RuntimeError(out or "claude mcp remove failed")
