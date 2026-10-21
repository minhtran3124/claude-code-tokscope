import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tokscope import dashboard, projects
from tokscope.ingest import connect

NOW = datetime.now(timezone.utc)

FAKE_LIST = """#!/bin/sh
echo "Checking MCP server health…"
echo ""
echo "claude.ai Linear: https://mcp.linear.app/mcp - ✔ Connected"
echo "claude.ai Notion: https://mcp.notion.com/mcp - ! Needs authentication"
echo "plugin:sentry:sentry: https://mcp.sentry.dev/mcp?token=SECRET123 (HTTP) - ✔ Connected"
echo "docs: npx docs-mcp - ⏸ Pending approval (run \\`claude\\` to approve)"
echo "api: https://api.example.com/mcp (HTTP) - ✘ Failed to connect"
"""


def ts(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class ProjectsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "h"
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "TOKSCOPE_HOME": str(self.tmp / "data")})
        env.start()
        self.addCleanup(env.stop)
        temp = mock.patch.object(projects, "_tempdir", return_value=str(self.tmp / "tmpdir"))  # the test's own home is in /tmp
        temp.start()
        self.addCleanup(temp.stop)
        self.app = self.home / "work" / "app"
        (self.app / ".git").mkdir(parents=True)
        (self.app / "apps" / "web").mkdir(parents=True)
        wt = self.home / "work" / "wt-feature"                      # a linked worktree of app, elsewhere on disk
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {self.app}/.git/worktrees/wt-feature\n")
        (self.home / "notes").mkdir(parents=True)
        (self.app / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "docs": {"command": "npx", "args": ["docs-mcp"]}, "api": {"type": "http", "url": "https://u:pw@api.example.com/mcp"}}}))
        (self.home / ".claude.json").write_text(json.dumps({
            "mcpServers": {"docs": {"command": "user-docs"}},       # same name as the project's: shadowed by it
            "projects": {str(self.app): {"mcpServers": {"api": {"type": "http", "url": "https://api.example.com/mcp",
                                                                  "headers": {"Authorization": "Bearer SECRET-TOKEN"}}},
                                         "disabledMcpServers": ["claude.ai Figma"]}}}))
        plugin = self.home / ".claude" / "plugins" / "cache" / "sentry"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"mcpServers": {"sentry": {"type": "http", "url": "https://mcp.sentry.dev/mcp"}}}))
        (self.home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"sentry@official": [{"scope": "user", "installPath": str(plugin)}]}}))
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"sentry@official": True}}))
        self.conn = connect(self.tmp / "t.db")
        sessions = [("s1", "-app", self.app), ("s2", "-app-web", self.app / "apps" / "web"), ("s3", "-wt", wt),
                    ("s4", "-app-eval-wt-gone", self.app / ".eval-wt-gone"), ("s5", "-notes", self.home / "notes"),
                    ("s6", "-tmp-x", self.tmp / "tmpdir" / "x"), ("s7", "-u-tokscope-bench-s1", self.app)]
        for sid, proj, cwd in sessions:
            self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts, last_ts) VALUES (?,?,?,?,1,?)",
                              (sid, proj, str(cwd), sid, ts(1)))
            self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, "
                              "cache_write_5m, cache_write_1h, cost_usd) VALUES (?,?,?,'claude-opus-5-5',1,1000,0,0,0,0,0.5)",
                              (sid, sid, ts(1)))
        calls = [("s1", "mcp__api__get", 400), ("s2", "mcp__api__get", 400), ("s1", "mcp__plugin_sentry_sentry__search", 4000),
                 ("s1", "mcp__claude_ai_Linear__get_issue", 800), ("s7", "mcp__docs__read", 99999)]
        for i, (sid, name, chars) in enumerate(calls):
            self.conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, prompt_idx, name, result_chars) VALUES (?,?,1,?,?)",
                              (sid, f"t{i}", name, chars))
        self.conn.commit()

    def app_group(self):
        return next(g for g in projects.discover(self.conn) if g["name"] == "app")

    def test_worktrees_subfolders_and_gone_eval_copies_fold_into_their_repository(self):
        found = projects.discover(self.conn)
        self.assertEqual([g["name"] for g in found], ["app", "notes", "Temporary folders"])
        app = found[0]
        self.assertEqual(app["sessions"], 4)                         # s1-s4; the benchmark session s7 is left out
        self.assertEqual(len(app["folders"]), 4)
        self.assertAlmostEqual(app["usd"], 2.0)

    def test_servers_show_their_source_use_and_shadowing_and_never_a_secret(self):
        rows = {(e["name"], e["source"]): e for e in projects.servers(self.app_group())}
        self.assertEqual(rows[("api", "local")]["calls"], 2)          # local wins over the project's api
        self.assertTrue(rows[("api", "project")]["shadowed"])
        self.assertTrue(rows[("docs", "user")]["shadowed"])
        self.assertEqual(rows[("docs", "project")]["flag"], "never used here")   # the bench session's calls do not count
        self.assertEqual(rows[("sentry", "plugin sentry")]["calls"], 1)
        self.assertEqual(rows[("Linear", "connector")]["calls"], 1)
        self.assertTrue(rows[("Figma", "connector")]["disabled"])
        self.assertEqual(rows[("api", "local")]["secrets"], ["Authorization"])
        self.assertEqual(rows[("api", "project")]["target"], "api.example.com")  # user:password dropped from the URL
        page = dashboard._project_view(self.app_group())
        self.assertNotIn("SECRET", page)
        self.assertNotIn("pw@", page)

    def test_the_health_check_adds_its_status_and_the_servers_only_it_knows(self):
        fake = self.tmp / "claude"
        fake.write_text(FAKE_LIST)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        status = projects.health(self.app, str(fake))
        self.assertEqual(status["plugin:sentry:sentry"], "✔ Connected")
        self.assertNotIn("SECRET123", json.dumps(status))
        rows = {(e["name"], e["source"]): e for e in projects.servers(self.app_group(), status)}
        self.assertEqual(rows[("sentry", "plugin sentry")]["status"], "✔ Connected")
        self.assertEqual(rows[("docs", "project")]["status"], "⏸ Pending approval (run `claude` to approve)")
        self.assertEqual(rows[("Notion", "connector")]["flag"], "never used here")    # known from the check only
        self.assertEqual(rows[("Linear", "connector")]["status"], "✔ Connected")
        page = dashboard._project_view(self.app_group())
        self.assertIn('class="st ok"><span class="pill">✔ Connected</span>', page)
        self.assertIn('class="st bad"><span class="pill">✘ Failed to connect</span>', page)

    def test_the_list_and_api_show_every_project_only_at_the_full_level(self):
        page = dashboard.page_projects(self.conn, dashboard.Filters({}), {}, "full")
        self.assertIn("2 projects from your sessions", page)
        self.assertIn("Temporary folders", page)
        self.assertIn("Projects are hidden", dashboard.page_projects(self.conn, dashboard.Filters({}), {}, "redacted"))
        api = dashboard.api(self.conn, "projects", {}, "")
        self.assertEqual(api[0]["name"], "app")
        self.assertNotIn("SECRET", json.dumps(api))


FAKE_CLI = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
if "remove" in sys.argv and "nope" in sys.argv:
    print("No MCP server found with name: nope in local config"); sys.exit(1)
if "add-json" in sys.argv and "taken" in sys.argv:
    print("MCP server taken already exists in local config; its header was Bearer sk-live-123456"); sys.exit(1)
print("Added stdio MCP server")
"""


class ChangeTest(ProjectsTest):
    def setUp(self):
        super().setUp()
        fake = self.tmp / "cli"
        fake.write_text(FAKE_CLI)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.cli, self.calls = str(fake), self.tmp / "calls.jsonl"
        os.environ["FAKE_LOG"] = str(self.calls)
        self.addCleanup(os.environ.pop, "FAKE_LOG", None)

    def ran(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_add_runs_add_json_in_the_project_with_its_scope_and_logs_no_value(self):
        form = {"name": "docs2", "scope": "project", "transport": "stdio", "command": "npx", "args": ["-y", "docs-mcp", ""],
                "pairs": [{"key": "API_KEY", "value": "${DOCS_KEY}"}, {"key": "", "value": "ignored"}]}
        self.assertEqual(projects.add(self.app, form, self.cli), ("docs2", "project"))
        call = self.ran()[0]
        self.assertEqual(call["argv"][:5], ["mcp", "add-json", "-s", "project", "docs2"])
        self.assertEqual(json.loads(call["argv"][5]), {"type": "stdio", "command": "npx", "args": ["-y", "docs-mcp"],
                                                       "env": {"API_KEY": "${DOCS_KEY}"}})
        self.assertEqual(Path(call["cwd"]).resolve(), self.app.resolve())
        log = (self.tmp / "data" / "data" / "mcp-changes.jsonl").read_text()
        self.assertIn('"action": "add", "name": "docs2", "scope": "project", "ok": true', log)
        self.assertNotIn("DOCS_KEY", log)

    def test_an_error_from_claude_never_carries_a_value_back(self):
        form = {"name": "taken", "scope": "local", "transport": "http", "url": "https://x.example/mcp",
                "pairs": [{"key": "Authorization", "value": "Bearer sk-live-123456"}]}
        with self.assertRaises(RuntimeError) as e:
            projects.add(self.app, form, self.cli)
        self.assertIn("already exists", str(e.exception))
        self.assertNotIn("sk-live-123456", str(e.exception))

    def test_bad_forms_are_refused_before_claude_runs(self):
        for form in ({"name": "a b", "scope": "local", "transport": "stdio", "command": "x"},
                     {"name": "a", "scope": "global", "transport": "stdio", "command": "x"},
                     {"name": "a", "scope": "local", "transport": "ws", "command": "x"},
                     {"name": "a", "scope": "local", "transport": "stdio", "command": ""},
                     {"name": "a", "scope": "local", "transport": "http", "url": "file:///etc/passwd"},
                     {"name": "a", "scope": "local", "transport": "stdio", "command": "x", "pairs": [{"key": "A B", "value": "1"}]},
                     {"name": "a", "scope": "local", "transport": "http", "url": "https://x", "pairs": [{"key": "X", "value": "1\nY: 2"}]}):
            with self.assertRaises(ValueError, msg=form):
                projects.add(self.app, form, self.cli)
        with self.assertRaises(ValueError):
            projects.remove(self.app, "docs", "plugin", self.cli)
        self.assertFalse(self.calls.exists())

    def test_remove_names_its_scope_and_reports_claude_s_answer(self):
        projects.remove(self.app, "docs", "user", self.cli)
        self.assertEqual(self.ran()[0]["argv"], ["mcp", "remove", "-s", "user", "docs"])
        with self.assertRaisesRegex(RuntimeError, "No MCP server found"):
            projects.remove(self.app, "nope", "local", self.cli)

    def test_the_page_offers_remove_only_where_claude_mcp_can_remove(self):
        page = dashboard._project_view(self.app_group())
        self.assertIn('data-mcp-remove="api" data-scope="local"', page)
        self.assertIn('data-mcp-remove="docs" data-scope="user"', page)
        self.assertNotIn('data-mcp-remove="sentry"', page)
        self.assertIn("with the plugin: /plugin", page)
        self.assertIn('id="mcp-form"', page)


if __name__ == "__main__":
    unittest.main()
