import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tokscope.integrations import managed
from tokscope.web import dashboard
from http.server import BaseHTTPRequestHandler
from tokscope.core.ingest import connect
from tokscope.paths import ASSETS

DEP = {"id": "depl_01Abc", "name": "Daily brief", "status": "paused", "paused_reason": {"type": "manual"},
       "agent": {"id": "agent_01A", "type": "agent", "version": 1}, "budget": {"type": "limit", "max_list_cost": {"amount": "2500", "currency": "USD"}},
       "schedule": {"type": "cron", "expression": "45 7 * * 1-5", "timezone": "Asia/Ho_Chi_Minh", "upcoming_runs_at": ["2026-10-23T00:45:00Z"]}}
AGENT = {"id": "agent_01A", "name": "Brief <writer>", "model": {"id": "claude-haiku-5-5", "effort": {"type": "medium"}},
         "mcp_servers": [{"name": "github", "type": "url", "url": "https://api.githubcopilot.com/mcp/"}], "skills": [], "system": "secret prompt",
         "description": None, "version": 1, "updated_at": "2026-10-22T09:00:00Z", "execution_identity": {"type": "service_account"},
         "multiagent": None, "metadata": {"source": "cookbook"},
         "tools": [{"type": "agent_toolset_20260401", "default_config": {"enabled": True, "permission_policy": {"type": "always_allow"}},
                    "configs": [{"name": "web_search", "enabled": False, "permission_policy": {"type": "always_allow"}}]},
                   {"type": "mcp_toolset", "mcp_server_name": "github",
                    "default_config": {"enabled": True, "permission_policy": {"type": "always_ask"}}}]}


def ses(sid, dep="depl_01Abc", cost="8"):
    return {"id": sid, "title": "Daily brief", "status": "idle", "created_at": "2026-10-22T09:53:54.650723Z",
            "agent": {"id": "agent_01A"}, "deployment_id": dep,
            "usage": {"input_tokens": 10, "output_tokens": 100, "cache_read_input_tokens": 1000, "active_seconds": 63.5,
                      "cache_creation": {"ephemeral_5m_input_tokens": 50, "ephemeral_1h_input_tokens": 0},
                      "list_cost": {"amount": cost, "currency": "USD"}}}


def fake(calls=None, sessions=None):
    def run(args):
        if calls is not None:
            calls.append(args)
        return {"beta:sessions": sessions if sessions is not None else [ses("sesn_1"), ses("sesn_2", cost="12"), ses("sesn_3", dep=None)],
                "beta:deployments": [DEP], "beta:agents": [AGENT]}[args[0]]
    return run


class ManagedReadTest(unittest.TestCase):
    def setUp(self):
        managed.forget()
        self.addCleanup(managed.forget)

    def test_sessions_sum_into_their_deployment_and_agent_in_dollars(self):
        data = managed.read(run=fake())
        (d,), (a,) = data["deployments"], data["agents"]
        self.assertEqual(d["sessions"], 2)                      # the third session has no deployment
        self.assertEqual(d["tokens"], 2 * 1160)
        self.assertAlmostEqual(d["cost"], 0.20)                 # "8" and "12" are cents
        self.assertEqual(d["budget"], 25.0)
        self.assertEqual((d["cron"], d["tz"], d["paused"]), ("45 7 * * 1-5", "Asia/Ho_Chi_Minh", "manual"))
        self.assertEqual((a["sessions"], a["model"], a["effort"], a["mcp"]), (3, "claude-haiku-5-5", "medium", ["github"]))
        self.assertEqual((a["system"], a["version"], a["runs_as"]), ("secret prompt", 1, "service_account"))
        self.assertEqual([(t["type"], t["server"], t["enabled"], t["policy"], t["changed"]) for t in a["tools"]],
                         [("agent_toolset_20260401", "", True, "always allow", [("web_search", False, "always allow")]),
                          ("mcp_toolset", "github", True, "always ask", [])])

    def test_only_list_commands_run_and_the_result_is_kept(self):
        calls = []
        managed.read(run=fake(calls))
        managed.read(run=fake(calls))
        self.assertEqual([c[:2] for c in calls], [["beta:sessions", "list"], ["beta:deployments", "list"], ["beta:agents", "list"]])
        managed.read(refresh=True, run=fake(calls))
        self.assertEqual(len(calls), 6)

    def test_an_error_becomes_text_to_show(self):
        def broken(args):
            raise RuntimeError("401 Unauthorized")
        self.assertEqual(managed.read(run=broken)["error"], "401 Unauthorized")

    def test_data_of_an_unknown_shape_becomes_text_to_show(self):
        for bad in ([ses("sesn_1") | {"usage": {"input_tokens": "many"}}], ["not an object"],
                    [ses("sesn_1") | {"usage": {"active_seconds": "long"}}]):
            managed.forget()
            self.assertIn("cannot read", managed.read(run=fake(sessions=bad))["error"])

    def test_ant_runs_with_an_argument_list_and_a_timeout(self):
        done = subprocess.CompletedProcess([], 0, stdout='{"id": "a"}\n{"id": "b"}\n', stderr="")
        with mock.patch.object(managed, "_ant", return_value="/bin/ant"), \
                mock.patch.object(managed.subprocess, "run", return_value=done) as run:
            self.assertEqual(managed._run(["beta:agents", "list"]), [{"id": "a"}, {"id": "b"}])
        args, kw = run.call_args
        self.assertEqual(args[0], ["/bin/ant", "beta:agents", "list", "--format", "jsonl"])
        self.assertEqual(kw["timeout"], managed.TIMEOUT)
        self.assertNotIn("shell", kw)

    def test_ant_in_the_user_bin_folder_is_found_without_it_on_path(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home, empty = Path(tmp.name) / "home", Path(tmp.name) / "path"  # an empty PATH: no other ant can be found
        exe = home / ".local" / "bin" / "ant"
        exe.parent.mkdir(parents=True)
        empty.mkdir()
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        with mock.patch.dict(os.environ, {"HOME": str(home), "PATH": str(empty)}):
            self.assertEqual(managed._ant(), str(exe))
            exe.unlink()
            self.assertIsNone(managed._ant())

    def test_missing_ant_and_a_failed_command_raise_readable_errors(self):
        with mock.patch.object(managed, "_ant", return_value=None):
            self.assertRaisesRegex(RuntimeError, "not installed", managed._run, ["beta:agents", "list"])
        with mock.patch.object(managed, "_ant", return_value="/bin/ant"), \
                mock.patch.object(managed.subprocess, "run", side_effect=OSError(8, "Exec format error")):
            self.assertRaisesRegex(RuntimeError, "could not start: Exec format error", managed._run, ["beta:agents", "list"])
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="GET ...: 401 Unauthorized\n")
        with mock.patch.object(managed, "_ant", return_value="/bin/ant"), \
                mock.patch.object(managed.subprocess, "run", return_value=failed):
            self.assertRaisesRegex(RuntimeError, "401 Unauthorized", managed._run, ["beta:agents", "list"])


class ActTest(unittest.TestCase):
    def setUp(self):
        managed.forget()
        self.addCleanup(managed.forget)

    def test_pause_runs_one_deployment_command_and_clears_the_cache(self):
        managed.read(run=fake())
        calls = []
        status = managed.act("pause", "depl_01Abcdefgh", run=lambda a: calls.append(a) or [{"status": "paused"}])
        self.assertEqual(status, "paused")
        self.assertEqual(calls, [["beta:deployments", "pause", "--deployment-id", "depl_01Abcdefgh"]])
        self.assertEqual(managed._cache, {})                     # the next read shows the new status

    def test_a_failed_write_still_clears_the_cache(self):
        managed.read(run=fake())
        def broken(args):
            raise RuntimeError("409 Conflict")
        self.assertRaisesRegex(RuntimeError, "409", managed.act, "unpause", "depl_01Abcdefgh", broken)
        self.assertEqual(managed._cache, {})

    def test_a_failure_after_the_write_landed_counts_as_done(self):
        calls = []
        def late(args):
            calls.append(args[:2])
            if args[1] == "pause":
                raise RuntimeError("ant did not answer in 30 s")
            return [{"status": "paused"}]
        self.assertEqual(managed.act("pause", "depl_01Abcdefgh", late), "paused")
        self.assertEqual(calls, [["beta:deployments", "pause"], ["beta:deployments", "retrieve"]])

    def test_a_failure_that_left_the_state_alone_is_still_an_error(self):
        def refused(args):
            if args[1] == "unpause":
                raise RuntimeError("409 Conflict")
            return [{"status": "paused"}]
        self.assertRaisesRegex(RuntimeError, "409", managed.act, "unpause", "depl_01Abcdefgh", refused)

    def test_only_pause_and_unpause_of_a_deployment_id_reach_ant(self):
        never = mock.Mock(side_effect=AssertionError("ran ant"))
        for action, dep in (("archive", "depl_01Abcdefgh"), ("run", "depl_01Abcdefgh"), ("pause", "depl_01Abc --profile x"),
                            ("pause", "agent_01Abcdefgh"), ("pause", "--help"), ("pause", "depl_01Abcdefgh\n"), ("pause", None), ("pause", ["depl_01Abcdefgh"])):
            self.assertRaises(ValueError, managed.act, action, dep, never)
        never.assert_not_called()


class WriteRouteTest(unittest.TestCase):
    def setUp(self):
        managed.forget()
        self.addCleanup(managed.forget)
        self.tmp = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"TOKSCOPE_HOME": str(self.tmp / "home"), "HOME": str(self.tmp / "h")})
        env.start()
        self.addCleanup(env.stop)
        self.calls = []
        ant = mock.patch.object(managed, "_run", lambda a: self.calls.append(a) or [{"status": "paused"}])
        ant.start()
        self.addCleanup(ant.stop)
        connect(self.tmp / "t.db").close()
        (self.tmp / "projects").mkdir()
        self.live = dashboard.Live(self.tmp / "t.db", ASSETS / "phases.json", 60, projects_dir=self.tmp / "projects")
        self.serve("full")

    def serve(self, level):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.port = server.server_address[1]
        server.RequestHandlerClass = dashboard.handler(self.tmp / "t.db", self.live, self.port, level, token="tok")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.good = {"Origin": f"http://127.0.0.1:{self.port}", "X-Tokscope-Token": "tok", "Content-Type": "application/json"}

    def post(self, path, body, headers):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_the_write_needs_this_origin_the_page_token_and_a_deployment_id(self):
        url, body = "/api/managed/deployments/pause", {"id": "depl_01Abcdefgh"}
        self.assertEqual(self.post(url, body, {**self.good, "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post(url, body, {**self.good, "X-Tokscope-Token": "guess"})[0], 403)
        self.assertEqual(self.post(url, {"id": "depl_x; rm -rf ~"}, self.good)[0], 400)
        self.assertEqual(self.post("/api/managed/deployments/archive", body, self.good)[0], 404)
        self.assertEqual(self.calls, [])                          # nothing ran yet
        self.assertEqual(self.post(url, body, self.good), (200, {"status": "paused"}))
        self.assertEqual(self.calls, [["beta:deployments", "pause", "--deployment-id", "depl_01Abcdefgh"]])

    def test_below_full_the_write_is_refused(self):
        self.serve("redacted")
        self.assertEqual(self.post("/api/managed/deployments/unpause", {"id": "depl_01Abcdefgh"}, self.good)[0], 403)
        self.assertEqual(self.calls, [])


class ManagedPageTest(unittest.TestCase):
    def setUp(self):
        managed.forget()
        self.addCleanup(managed.forget)

    def test_the_full_level_lists_all_three_and_escapes_names(self):
        with mock.patch.object(managed, "_run", fake()):
            body = dashboard.page_managed({}, "full")
        for part in ('id="deployments"', 'id="managed-sessions"', 'id="agents"', "title=\"depl_01Abc\"", "dep-st\">paused <button",
                     "45 7 * * 1-5 Asia/Ho_Chi_Minh", "$25.00", "Brief &lt;writer&gt;", "haiku-5-5 · medium"):
            self.assertIn(part, body)
        self.assertNotIn("secret prompt", body)
        self.assertIn('data-dep-act="unpause" data-dep="depl_01Abc" data-name="Daily brief">Unpause</button>', body)

    def test_an_agent_name_opens_its_configuration(self):
        with mock.patch.object(managed, "_run", fake()):
            self.assertIn('<a href="/managed?agent=agent_01A">Brief &lt;writer&gt;</a>', dashboard.page_managed({}, "full"))
            body = dashboard.page_managed({"agent": ["agent_01A"]}, "full")
        for part in ('id="agent-config"', "claude-haiku-5-5 · medium effort", "service account", "v1 · updated",
                     '<pre class="answer">secret prompt</pre>', "<h3>Built-in tools</h3>",
                     "<dt>Default</dt><dd>always allow</dd><dt>Set apart</dt><dd>web_search: off</dd>",
                     "<h3>MCP tools</h3>", "<code>github</code></dd><dt>URL</dt><dd><code>https://api.githubcopilot.com/mcp/</code>",
                     "<dd>always ask</dd>",
                     "<dt>source</dt><dd>cookbook</dd>", 'href="/managed?refresh=1&amp;agent=agent_01A"'):
            self.assertIn(part, body)
        self.assertNotIn('id="deployments"', body)

    def test_the_configuration_is_escaped(self):
        agents = [AGENT | {"system": "</pre><script>x</script>", "description": "<b>d</b>", "metadata": {"<k>": "<v>"}}]
        with mock.patch.object(managed, "_run", lambda a: {"beta:agents": agents}.get(a[0], [])):
            body = dashboard.page_managed({"agent": ["agent_01A"]}, "full")
        self.assertIn("&lt;/pre&gt;&lt;script&gt;x&lt;/script&gt;</pre>", body)
        self.assertNotIn("<script>x", body)
        self.assertIn("&lt;b&gt;d&lt;/b&gt;", body)
        self.assertIn("<dt>&lt;k&gt;</dt><dd>&lt;v&gt;</dd>", body)

    def test_odd_shapes_and_a_nameless_server_do_not_break_the_view(self):
        agents = [AGENT | {"metadata": ["x"], "description": {"a": 1}, "system": None,
                           "mcp_servers": [{"url": "https://nameless.example/"}],
                           "tools": [{"type": "agent_toolset_20260401"}]}]
        with mock.patch.object(managed, "_run", lambda a: {"beta:agents": agents}.get(a[0], [])):
            body = dashboard.page_managed({"agent": ["agent_01A"]}, "full")
        self.assertIn('id="agent-config"', body)
        self.assertIn("<code>https://nameless.example/</code>", body)   # listed though the built-in toolset has no server

    def test_an_unknown_agent_says_so(self):
        with mock.patch.object(managed, "_run", fake()):
            body = dashboard.page_managed({"agent": ['agent_"<x>']}, "full")
        self.assertIn("No such agent", body)
        self.assertIn("agent_&quot;&lt;x&gt;", body)
        self.assertIn('href="/managed?refresh=1&amp;agent=agent_%22%3Cx%3E"', body)

    def test_only_active_and_paused_deployments_get_a_button(self):
        deps = [DEP | {"id": "depl_01Act", "status": "active", "name": 'A "quoted" <one>'}, DEP | {"id": "depl_01Arc", "status": "archived"}]
        with mock.patch.object(managed, "_run", lambda a: {"beta:deployments": deps}.get(a[0], [])):
            body = dashboard.page_managed({}, "full")
        self.assertIn('data-dep-act="pause" data-dep="depl_01Act" data-name="A &quot;quoted&quot; &lt;one&gt;">Pause</button>', body)
        self.assertEqual(body.count("data-dep-act="), 1)            # archived: no write

    def test_a_reason_other_than_manual_sits_outside_the_unbreakable_part(self):
        deps = [DEP | {"paused_reason": {"type": "budget_reached"}}]
        with mock.patch.object(managed, "_run", lambda a: {"beta:deployments": deps}.get(a[0], [])):
            body = dashboard.page_managed({}, "full")
        self.assertIn('>Unpause</button></span> <span class="note dep-why">(budget reached)</span>', body)

    def test_below_full_the_page_never_runs_ant(self):
        with mock.patch.object(managed, "_run", side_effect=AssertionError("ran ant")):
            self.assertIn("full level only", dashboard.page_managed({}, "redacted"))
            self.assertIn("full level only", dashboard.page_managed({"agent": ["agent_01A"]}, "redacted"))

    def test_an_error_shows_the_sign_in_hint(self):
        with mock.patch.object(managed, "_run", side_effect=RuntimeError("ant is not installed")):
            body = dashboard.page_managed({}, "full")
        self.assertIn("ant auth login", body)
        self.assertIn("ant is not installed", body)

    def test_empty_lists_say_so(self):
        with mock.patch.object(managed, "_run", lambda args: []):
            body = dashboard.page_managed({}, "full")
        self.assertIn("No deployments", body)
        self.assertIn("No agents", body)


if __name__ == "__main__":
    unittest.main()
