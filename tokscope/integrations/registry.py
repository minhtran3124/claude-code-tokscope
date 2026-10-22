"""Search the official MCP Registry and turn a server into the dashboard's add-server form.

The dashboard asks the registry (registry.modelcontextprotocol.io, API v0.1) on your behalf: only the search words
leave the machine. Each result becomes one form per way to run it: a package (npm through npx, pypi through uvx,
oci through docker) or a remote URL. The form goes through the same checks and `claude mcp add-json` as a server you
type in; nothing is installed from here. Secret variables and headers stay empty: you type the value or a ${VAR}."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://registry.modelcontextprotocol.io/v0.1/servers"
TIMEOUT = 30  # the registry answers in 1 to 25 seconds
CACHE_S = 600
RUNNERS = {"npm": "npx", "pypi": "uvx", "oci": "docker"}
_cache = {}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "tokscope", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def _name(full):
    """io.github.someone/filesystem-server -> filesystem-server, fit for `claude mcp add-json`."""
    tail = full.rsplit("/", 1)[-1].lower()
    return re.sub(r"[^a-z0-9_-]+", "-", tail).strip("-")[:64] or "server"


def _arg(a):
    """A registry argument as command-line words; a required one with no value becomes a <hint> to fill in."""
    value = a.get("value") or a.get("default")
    if value is None and a.get("isRequired"):
        value = f"<{a.get('valueHint') or a.get('name') or 'value'}>"
    if a.get("type") == "named":
        return [a["name"], str(value)] if value is not None else []
    return [str(value)] if value is not None else []


def _pairs(items):
    return [{"key": i.get("name", ""), "secret": bool(i.get("isSecret")), "required": bool(i.get("isRequired")),
             "description": (i.get("description") or "")[:200], "value": "" if i.get("isSecret") else str(i.get("default") or "")}
            for i in items if i.get("name")]


def _package(p):
    kind, runner = p.get("registryType"), p.get("runtimeHint") or RUNNERS.get(p.get("registryType"))
    if kind not in RUNNERS or (p.get("transport") or {}).get("type", "stdio") != "stdio":
        return None  # a package that serves HTTP itself, or a registry type this form cannot run
    ident, version = p.get("identifier", ""), p.get("version")
    runtime = [w for a in p.get("runtimeArguments", []) for w in _arg(a)]
    env = _pairs(p.get("environmentVariables", []))
    if kind == "npm":
        target = [f"{ident}@{version}" if version else ident]
        runtime = runtime or ["-y"]
    elif kind == "pypi":
        target = [f"{ident}=={version}" if version else ident]
    else:  # docker passes each variable through with -e NAME
        target = [f"{ident}:{version}" if version and ":" not in ident else ident]
        runtime = runtime or ["run", "-i", "--rm", *[w for e in env for w in ("-e", e["key"])]]
    if any(ident and ident in w for w in runtime):  # "uvx --from pkg==1.0 cmd" names the package already
        target = []
    args = runtime + target + [w for a in p.get("packageArguments", []) for w in _arg(a)]
    return {"label": f"{kind} package {ident}", "transport": "stdio", "command": runner, "args": args, "url": "", "pairs": env}


def _remote(r):
    kind = {"streamable-http": "http", "http": "http", "sse": "sse"}.get(r.get("type"))
    if not kind or not str(r.get("url", "")).startswith(("http://", "https://")):
        return None
    return {"label": f"remote {kind} {urllib.parse.urlsplit(r['url']).netloc}", "transport": kind, "command": "", "args": [],
            "url": r["url"], "pairs": _pairs(r.get("headers", []))}


def normalize(entry):
    s = entry.get("server", {})
    options = [o for o in [*map(_package, s.get("packages", [])), *map(_remote, s.get("remotes", []))] if o]
    repo = (s.get("repository") or {}).get("url", "")
    return {"id": s.get("name", ""), "title": s.get("title") or s.get("name", ""), "name": _name(s.get("name", "")),
            "description": (s.get("description") or "")[:400], "version": s.get("version", ""),
            "website": s.get("websiteUrl") or "", "repository": repo if repo.startswith("https://") else "", "options": options}


def search(q, limit=12, fetch=_get):
    """Latest versions matching q, each with its install options; ones this form cannot run are left out."""
    q = str(q or "").strip()[:100]
    key = (q, limit)
    if key in _cache and time.time() - _cache[key][0] < CACHE_S:
        return _cache[key][1]
    url = f"{API}?{urllib.parse.urlencode({'search': q, 'version': 'latest', 'limit': limit} if q else {'version': 'latest', 'limit': limit})}"
    try:
        data = fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise RuntimeError(f"the MCP Registry did not answer ({getattr(e, 'reason', e)})") from e
    out = [n for n in map(normalize, data.get("servers", [])) if n["options"]]
    _cache[key] = (time.time(), out)
    return out
