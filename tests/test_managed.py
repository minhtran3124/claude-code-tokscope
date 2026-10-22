import subprocess
import unittest
from unittest import mock

from tokscope import dashboard, managed

DEP = {"id": "depl_01Abc", "name": "Daily brief", "status": "paused", "paused_reason": {"type": "manual"},
       "agent": {"id": "agent_01A", "type": "agent", "version": 1}, "budget": {"type": "limit", "max_list_cost": {"amount": "2500", "currency": "USD"}},
       "schedule": {"type": "cron", "expression": "45 7 * * 1-5", "timezone": "Asia/Ho_Chi_Minh", "upcoming_runs_at": ["2026-10-23T00:45:00Z"]}}
AGENT = {"id": "agent_01A", "name": "Brief <writer>", "model": {"id": "claude-haiku-5-5", "effort": {"type": "medium"}},
         "mcp_servers": [{"name": "github", "type": "url", "url": "https://api.githubcopilot.com/mcp/"}], "skills": [], "system": "secret prompt"}


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
        self.assertNotIn("system", a)                           # the prompt text never reaches the page

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
        with mock.patch.object(managed.shutil, "which", return_value="/bin/ant"), \
                mock.patch.object(managed.subprocess, "run", return_value=done) as run:
            self.assertEqual(managed._run(["beta:agents", "list"]), [{"id": "a"}, {"id": "b"}])
        args, kw = run.call_args
        self.assertEqual(args[0], ["/bin/ant", "beta:agents", "list", "--format", "jsonl"])
        self.assertEqual(kw["timeout"], managed.TIMEOUT)
        self.assertNotIn("shell", kw)

    def test_missing_ant_and_a_failed_command_raise_readable_errors(self):
        with mock.patch.object(managed.shutil, "which", return_value=None):
            self.assertRaisesRegex(RuntimeError, "not installed", managed._run, ["beta:agents", "list"])
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="GET ...: 401 Unauthorized\n")
        with mock.patch.object(managed.shutil, "which", return_value="/bin/ant"), \
                mock.patch.object(managed.subprocess, "run", return_value=failed):
            self.assertRaisesRegex(RuntimeError, "401 Unauthorized", managed._run, ["beta:agents", "list"])


class ManagedPageTest(unittest.TestCase):
    def setUp(self):
        managed.forget()
        self.addCleanup(managed.forget)

    def test_the_full_level_lists_all_three_and_escapes_names(self):
        with mock.patch.object(managed, "_run", fake()):
            body = dashboard.page_managed({}, "full")
        for part in ('id="deployments"', 'id="managed-sessions"', 'id="agents"', "<code>depl_01Abc</code>", "paused (manual)",
                     "45 7 * * 1-5 Asia/Ho_Chi_Minh", "$25.00", "Brief &lt;writer&gt;", "haiku-5-5 · medium"):
            self.assertIn(part, body)
        self.assertNotIn("secret prompt", body)

    def test_below_full_the_page_never_runs_ant(self):
        with mock.patch.object(managed, "_run", side_effect=AssertionError("ran ant")):
            self.assertIn("full level only", dashboard.page_managed({}, "redacted"))

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
