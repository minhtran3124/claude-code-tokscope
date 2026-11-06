"""The HTTP server: GET pages and /api, POST writes behind host, origin and token checks, background ingest."""

import hmac
import html
import json
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from ...core import privacy, summary
from ...experiments import optimize
from ...features import library, projects, service
from ...features import live as livemod
from ...integrations import managed, registry
from ..theme import fonts
from ..theme.brand import FAVICON
from ...core.ingest import connect, ingest
from ..report.sections.sessions import _sessions_json
from .common import Filters, PAGES
from .pages import optimize as optpage
from .pages.overview import _days, _totals
from .shell import render, skills_moved


def summary_rows_response(conn, qs):
    """(code, body, content type) for /api/summary?by=&format=: the CLI's rows for the filter bar's filters."""
    one = lambda k, default: (qs.get(k) or [default])[0].strip()  # noqa: E731
    by, fmt = one("by", "phase"), one("format", "json")
    if by not in summary.SUMMARY_SQL or fmt not in ("json", "csv"):
        return 400, json.dumps({"error": "by is phase, skill, agent or model; format is json or csv"}), "application/json"
    try:
        limit = min(max(int(one("limit", str(summary.DEFAULT_LIMIT))), 1), 1000)
    except ValueError:
        return 400, json.dumps({"error": "limit is a number"}), "application/json"
    found = summary.rows(conn, by, *Filters(qs).cond(), limit)
    return (200, summary.to_csv(found), "text/csv; charset=utf-8") if fmt == "csv" else (200, summary.to_json(found), "application/json")


def api(conn, name, qs, stamp):
    f = Filters(qs)
    if name == "summary":
        cond, params = f.cond()
        t = _totals(conn, cond, params)
        return {"range": f.range, "tokens": t[0] or 0, "usd": t[1], "sessions": t[2], "output": t[3] or 0, "runs": t[4],
                "cache_read": t[5] or 0, "days": [{"day": d, "tokens": tk, "usd": u} for d, tk, u in _days(conn, f)]}
    if name == "projects":
        return [{"name": g["name"], "path": g["path"], "folders": [c for c, _ in g["folders"]], "sessions": g["sessions"],
                 "tokens": g["tokens"], "tokens_30d": g["recent"], "usd": round(g["usd"], 2), "last": g["last"],
                 "mcp": [{k: e[k] for k in ("name", "source", "transport", "calls", "tokens", "flag", "disabled", "status")}
                         for e in projects.servers(g, (projects.last_health(g["root"]) or (0, None))[1])]}
                for g in projects.discover(conn)]
    if name == "library":
        found = library.discover(conn)
        used = library.usage(conn, found)
        state = library.idle(conn, found)
        return [{"name": k["name"], "scope": k["scope"], "origin": k["origin"], "reason": k["reason"], "description": k["description"],
                 "path": str(k["folder"]), "loads": used.get(k["id"], (0, None))[0],
                 "status": state[k["id"]], "prefix_tokens_est": library.prefix(k)[1]} for k in found]
    if name == "sessions":
        cond, params = f.cond()
        return [{k: s[k] for k in ("id", "title", "start", "end", "prompts", "tokens", "output", "usd", "main", "agents", "runs")}
                for s in _sessions_json(conn, cond, params)]
    raise KeyError(name)


class Live:
    """Ingests new transcripts every `interval` seconds; `stamp` changes when the data does."""

    def __init__(self, db, phases, interval, projects_dir=None):
        self.db, self.phases, self.interval, self.projects_dir = db, phases, interval, projects_dir
        self.stamp = self._stamp()
        self.error = None

    def _stamp(self):
        conn = connect(self.db)
        try:
            n, last = conn.execute("SELECT count(*), max(ts) FROM requests").fetchone()
            sv = conn.execute("SELECT count(*), max(last_seen) FROM skill_versions").fetchone() if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone() else (0, "")
            return f"{n}:{last}:{sv[0]}"
        finally:
            conn.close()

    def tick(self):
        try:
            ingest(self.db, self.phases, self.projects_dir, log=lambda *_: None)
            self.stamp, self.error = self._stamp(), None
        except Exception as e:  # a half-written transcript or a locked db: keep serving, try again next tick
            self.error = str(e)

    def run(self):
        while True:
            time.sleep(self.interval)
            self.tick()


def post(db, path, body, level):
    """(code, JSON) for a write: an optimize run, a project's MCP servers, or pausing or unpausing a Managed Agents deployment."""
    if level != "full":
        return 403, {"error": "writes need the full privacy level"}
    if m := re.match(r"^api/projects/([0-9a-f]{10})/health$", path):
        conn = connect(db)
        try:
            g = next((g for g in projects.discover(conn) if g["id"] == m.group(1)), None)
        finally:
            conn.close()
        if not g or not g["root"] or not g["root"].is_dir():
            return 404, {"error": "no such project folder"}
        try:
            return 200, {"status": projects.health(g["root"], optimize._claude())}
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            return 502, {"error": f"claude mcp list failed: {e}"}
    if m := re.match(r"^api/projects/([0-9a-f]{10})/mcp(/remove)?$", path):
        conn = connect(db)
        try:
            g = next((g for g in projects.discover(conn) if g["id"] == m.group(1)), None)
        finally:
            conn.close()
        if not g or not g["root"] or not g["root"].is_dir():
            return 404, {"error": "no such project folder"}
        try:
            if m.group(2):
                projects.remove(g["root"], body.get("name"), body.get("scope"), optimize._claude())
            else:
                name, scope = projects.add(g["root"], body, optimize._claude())
                return 200, {"name": name, "scope": scope}
            return 200, {"ok": True}
        except ValueError as e:
            return 400, {"error": str(e)}
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            return 502, {"error": str(e)}
    if m := re.match(r"^api/managed/deployments/(pause|unpause)$", path):
        try:
            return 200, {"status": managed.act(m.group(1), body.get("id"))}
        except ValueError as e:
            return 400, {"error": str(e)}
        except RuntimeError as e:
            return 502, {"error": str(e)}
    if m := re.match(r"^api/service/(install|start|stop|autostart)$", path):
        try:
            act = m.group(1)
            if act == "autostart":
                return 200, {"status": service.set_autostart(bool(body.get("on")))}
            if act == "install":
                if service.is_mac():
                    return 400, {"error": "on macOS use File > Start at login in the app"}
                return 200, {"status": service.install(exe=service.CHECKOUT / "bin" / "tokscope", quote=True)}
            return 200, {"status": getattr(service, act)()}
        except RuntimeError as e:
            return 502, {"error": str(e)}
    if path == "optimize/start":
        return optpage.start(db, body)
    if path == "optimize/suite/generate":
        return optpage.suitegen_start(db, body)
    if path == "optimize/suite/status":
        return optpage.suitegen_state(db, body)
    if path == "optimize/suite/approve":
        return optpage.suitegen_approve(db, body)
    if m := re.match(r"^optimize/([A-Za-z0-9._-]+)/(approve|reject)$", path):
        return optpage.decide(db, m.group(1), m.group(2), body)
    return 404, {"error": "unknown endpoint"}


def handler(db, live, port, level, token=None):
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in allowed}
    token = token or secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code, body, kind="text/html; charset=utf-8"):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, to):
            self.send_response(302)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            # only this machine's browser: a page on another site cannot reach it by renaming itself (DNS rebinding)
            if self.headers.get("Host") not in allowed:
                return self._send(403, "tokscope serves this machine only")
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            name = url.path.strip("/") or "overview"
            if name in ("favicon.ico", "favicon.svg"):  # browsers ask before they read the page's icon link
                return self._send(200, FAVICON, "image/svg+xml")
            if m := re.match(r"^fonts/([^/]+)$", name):
                data = fonts.read(m.group(1))
                if data is None:
                    return self._send(404, "no such font")
                self.send_response(200)
                self.send_header("Content-Type", "font/woff2")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=31536000, immutable")
                self.end_headers()
                return self.wfile.write(data)
            if name == "api/registry":
                if level != "full":
                    return self._send(403, json.dumps({"error": "the full level only"}), "application/json")
                try:
                    found = registry.search((qs.get("q") or [""])[0])
                except RuntimeError as e:
                    return self._send(502, json.dumps({"error": str(e)}), "application/json")
                return self._send(200, json.dumps(found), "application/json")
            if name == "managed" and qs.get("refresh"):  # read ant again, then drop ?refresh so a reload does not
                managed.forget()
                pick = (qs.get("agent") or [""])[0]
                return self._redirect("/managed" + (f"?agent={quote(pick, safe='')}" if pick else ""))
            if name == "api/version":
                # pages poll this every 2 s: answer before the database (a redacted copy is a full backup)
                return self._send(200, json.dumps({"stamp": live.stamp, "error": live.error, "live": livemod.signature(livemod.running())}), "application/json")
            if name == "api/live":  # which sessions are open and busy right now (files in ~/.claude/sessions, not the database)
                return self._send(200, json.dumps({s["id"]: {"status": s["status"], "entry": s["entry"]} for s in livemod.running()}),
                                  "application/json")
            conn = privacy.redacted_copy(db, level) if level != "full" else connect(db)
            try:
                if name == "api/summary" and ("by" in qs or "format" in qs):  # without them, the totals api() gives
                    return self._send(*summary_rows_response(conn, qs))
                if name.startswith("api/"):
                    try:
                        return self._send(200, json.dumps(api(conn, name[4:], qs, live.stamp)), "application/json")
                    except KeyError:
                        return self._send(404, json.dumps({"error": "unknown endpoint"}), "application/json")
                if name == "skills":  # the Skills page moved into the Library
                    return self._redirect(skills_moved(conn, qs))
                if name not in PAGES:
                    return self._send(404, f"<p>No page {html.escape(name)}. Try <a href='/overview'>Overview</a>.</p>")
                return self._send(200, render(conn, name, qs, live.stamp, level, token))
            except sqlite3.OperationalError as e:
                return self._send(503, f"<p>The database is busy ({html.escape(str(e))}); reload in a moment.</p>")
            finally:
                conn.close()

        def do_POST(self):
            # a write needs this machine's host, this dashboard's origin, the token of a page it served and a JSON body:
            # another site's form or fetch fails the origin and token checks, and cannot set the header without CORS
            if self.headers.get("Host") not in allowed or self.headers.get("Origin") not in origins:
                return self._send(403, json.dumps({"error": "refused: not this dashboard"}), "application/json")
            if not hmac.compare_digest(self.headers.get("X-Tokscope-Token", ""), token):
                return self._send(403, json.dumps({"error": "refused: reload the page"}), "application/json")
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._send(415, json.dumps({"error": "send JSON"}), "application/json")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                return self._send(413, json.dumps({"error": "too large"}), "application/json")
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, json.dumps({"error": "bad JSON"}), "application/json")
            code, out = post(db, urlparse(self.path).path.strip("/"), body if isinstance(body, dict) else {}, level)
            return self._send(code, json.dumps(out), "application/json")

    return Handler


class QuietServer(ThreadingHTTPServer):
    """A browser that reloads or closes a tab while a page is being written drops the connection: that is not an error
    of the dashboard, so it prints nothing. Every other error in a request is printed as usual."""

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def serve(db, phases, port=8765, interval=10.0, open_browser=True, level="full", log=print, projects_dir=None):
    live = Live(db, phases, interval, projects_dir)
    live.tick()  # start from fresh data
    server = QuietServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    port = server.server_address[1]  # the real one when asked for port 0
    server.RequestHandlerClass = handler(db, live, port, level)
    threading.Thread(target=live.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}/overview"
    log(f"tokscope dashboard on {url} (this machine only; ingests every {interval:g}s; Ctrl+C stops it)")
    if open_browser:
        from ...cli import open_in_browser
        open_in_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
