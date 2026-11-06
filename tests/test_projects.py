import json
import os
import stat
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tokscope.features import projects
from tokscope.web import dashboard
from tokscope.web.dashboard.pages import projects as projects_page
from tokscope.core.ingest import connect

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

    def test_a_deleted_worktree_or_eval_copy_folds_into_its_repository_by_name(self):
        for cwd in (self.home / "work" / "app-worktrees" / "gone", self.app / ".claude" / "skills" / "x" / "eval",
                    self.home / "old" / "repo-worktrees" / "t1", self.home / "old" / "repo-worktrees" / "t2"):
            self.assertEqual(projects.root_of(cwd), self.app if cwd.is_relative_to(self.home / "work") else self.home / "old" / "repo")
        # a hidden folder of the home folder is not cut off
        self.assertEqual(projects.root_of(self.home / ".local" / "state" / "bot"), self.home / ".local" / "state" / "bot")

    def test_projects_json_ignores_folders_that_are_not_projects(self):
        (self.tmp / "data").mkdir(exist_ok=True)
        (self.tmp / "data" / "projects.json").write_text(json.dumps({"ignore": ["no*", "~/nothing/*"]}))
        self.assertEqual([g["name"] for g in projects.discover(self.conn)], ["app", "Temporary folders"])

    def test_hide_adds_the_folder_to_ignore_and_restore_takes_it_out_and_nothing_is_deleted(self):
        data = self.tmp / "data" / "projects.json"
        data.parent.mkdir(exist_ok=True)
        data.write_text(json.dumps({"ignore": ["keep*"], "other": 1}))
        pattern = projects.hide(self.app)
        self.assertEqual([g["name"] for g in projects.discover(self.conn)], ["notes", "Temporary folders"])
        self.assertEqual(json.loads(data.read_text()), {"ignore": ["keep*", pattern], "other": 1})
        projects.hide(self.app)                                       # twice: one entry
        self.assertEqual(projects.hidden().count(pattern), 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM sessions").fetchone()[0], 7)   # the stored sessions stay
        self.assertTrue(self.app.is_dir())
        projects.unhide(pattern)
        self.assertEqual([g["name"] for g in projects.discover(self.conn)], ["app", "notes", "Temporary folders"])
        with self.assertRaises(ValueError):
            projects.unhide("not-there")
        with self.assertRaises(ValueError):
            projects.hide(None)

    def test_a_folder_name_with_glob_characters_hides_only_itself(self):
        odd = self.home / "work" / "a[1]*"
        (odd / ".git").mkdir(parents=True)
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts, last_ts) VALUES ('so','-o',?,'o',1,?)", (str(odd), ts(1)))
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, cache_write_5m, "
                          "cache_write_1h, cost_usd) VALUES ('so','so',?,'claude-opus-5-5',1,1,0,0,0,0,0.1)", (ts(1),))
        self.conn.commit()
        projects.hide(odd)
        self.assertEqual(sorted(g["name"] for g in projects.discover(self.conn)), ["Temporary folders", "app", "notes"])

    def test_the_list_has_both_views_with_the_data_to_filter_and_sort_and_a_remove_for_real_projects(self):
        page = dashboard.page_projects(self.conn, dashboard.Filters({}), {}, "full")
        self.assertIn('id="proj-list"', page)
        self.assertIn('id="proj-cards"', page)
        self.assertEqual(page.count('class="pcard"'), 3)
        self.assertIn('data-tokens="', page)
        self.assertIn('id="proj-find"', page)
        self.assertEqual(page.count("data-proj-remove="), 4)        # app and notes, in the list and the cards; not the temporary folders
        self.assertIn("your folders are not deleted", page)
        projects.hide(self.app)
        page = dashboard.page_projects(self.conn, dashboard.Filters({}), {}, "full")
        self.assertIn("Removed from this list (1)", page)
        self.assertIn("data-proj-restore=", page)

    def test_the_post_routes_hide_and_restore(self):
        from tokscope.web.dashboard import server
        db = self.tmp / "t.db"
        self.conn.commit()
        gid = self.app_group()["id"]
        self.assertEqual(server.post(db, f"api/projects/{gid}/hide", {}, "full"), (200, {"ok": True}))
        self.assertEqual(server.post(db, f"api/projects/{gid}/hide", {}, "full")[0], 404)
        self.assertEqual(server.post(db, "api/projects/temp0000000/hide", {}, "full")[0], 404)
        self.assertEqual(server.post(db, "api/projects/unhide", {"pattern": projects.hidden()[0]}, "full"), (200, {"ok": True}))
        self.assertEqual(server.post(db, "api/projects/unhide", {"pattern": "x"}, "full")[0], 400)
        self.assertEqual(server.post(db, f"api/projects/{gid}/hide", {}, "redacted")[0], 403)

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
        page = projects_page._project_view(self.app_group())
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
        page = projects_page._project_view(self.app_group())
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

    def test_each_mcp_server_row_shows_its_p95_result_tokens_marked_as_an_estimate(self):
        page = projects_page._project_view(self.app_group())
        self.assertIn("≈p95 result", page)
        self.assertEqual(self.app_group()["mcp"]["plugin_sentry_sentry"]["p95"], 1000)   # 4000 chars at 4 per token
        self.assertIn('data-label="≈p95 result" title="~ estimate:', page)
        self.assertIn(">~1.0K</td>", page)

    def test_the_p95_is_taken_over_all_of_a_projects_folders_not_one_folder_s(self):
        for i, (sid, chars) in enumerate([("s1", 8000), ("s2", 40000), ("s3", 8000)]):   # app, app/apps/web, a worktree
            self.conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, prompt_idx, name, result_chars) VALUES (?,?,1,?,?)",
                              (sid, f"p{i}", "mcp__plugin_sentry_sentry__search", chars))
        self.conn.commit()
        sentry = self.app_group()["mcp"]["plugin_sentry_sentry"]
        self.assertEqual((sentry["calls"], sentry["p95"]), (4, 10000))   # the slowest call is in one folder only

    def test_the_page_offers_remove_only_where_claude_mcp_can_remove(self):
        page = projects_page._project_view(self.app_group())
        self.assertIn('data-mcp-remove="api" data-scope="local"', page)
        self.assertIn('data-mcp-remove="docs" data-scope="user"', page)
        self.assertNotIn('data-mcp-remove="sentry"', page)
        self.assertIn("with the plugin: /plugin", page)
        self.assertIn('id="mcp-form"', page)


class BaselineProjectTest(ProjectsTest):
    """Reuses the projects fixture: s1-s4 belong to `app`, each with one main-thread request of 1000 input tokens."""

    def test_the_baseline_ignores_sidechain_requests_and_prices_the_cache_write(self):
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, agent_id, input, output, cache_read, "
                          "cache_write_5m, cache_write_1h) VALUES ('s1','side',?, 'claude-opus-5-5','a1',99999,0,0,0,0)", (ts(2),))
        found = projects.discover(self.conn)
        projects.add_baselines(self.conn, found, 30)
        g = next(g for g in found if g["name"] == "app")
        self.assertEqual((g["base"]["n"], g["base"]["median"], g["base"]["p90"]), (4, 1000, 1000))
        self.assertAlmostEqual(g["base"]["cost"], 1000 * 4.0 * 1.25 / 1e6)
        page = projects_page._project_view(g)
        self.assertIn("Every new session starts at ~1.0K tokens (~$0.01)", page)
        self.assertIn("Estimate.", page)                              # the method is the tooltip

    def test_a_project_with_no_sessions_in_the_range_shows_no_baseline_and_no_error(self):
        found = projects.discover(self.conn)
        projects.add_baselines(self.conn, found, 30, now=time.time() + 400 * 86400)
        self.assertTrue(all(g["base"] is None for g in found))
        page = projects_page._project_view(found[0])
        self.assertIn("No sessions in this range.", page)
        self.assertNotIn("Every new session starts", page)

    def test_the_range_of_the_filter_bar_limits_the_sessions(self):
        self.conn.execute("UPDATE requests SET ts = ? WHERE session_id = 's1'", (ts(20),))
        found = projects.discover(self.conn)
        projects.add_baselines(self.conn, found, 7)
        self.assertEqual(found[0]["base"]["n"], 3)
        projects.add_baselines(self.conn, found, None)
        self.assertEqual(found[0]["base"]["n"], 4)

    def test_definitions_split_per_server_and_unused_ones_sum_into_the_finding(self):
        self.conn.executemany("INSERT INTO mcp_defs VALUES ('s1', ?, ?, ?)",
                              [("docs", 3, 4000), ("api", 2, 2000), ("claude_ai_Notion", 1, 2400)])
        found = projects.discover(self.conn)
        projects.add_baselines(self.conn, found, 30)
        g = next(g for g in found if g["name"] == "app")
        rows = {(e["name"], e["source"]): e for e in projects.servers(g, {"claude.ai Notion": "✔ Connected"})}
        self.assertEqual(rows[("docs", "project")]["def_tokens"], 1000)     # about 4 characters per token
        self.assertEqual(rows[("api", "local")]["def_tokens"], 500)
        self.assertIsNone(rows[("Linear", "connector")]["def_tokens"])      # no definition seen
        servers, tokens, usd = projects.idle_cost(g, list(rows.values()))
        self.assertEqual((servers, tokens), (2, 1600))                      # docs and Notion were never called
        self.assertAlmostEqual(usd, 1600 * 4.0 * 1.25 / 1e6)
        page = projects_page._project_view(g)
        self.assertIn("≈Definition tokens", page)
        self.assertIn("1 unused MCP server adds ~1.0K tokens (~$0.01) to every session start in this project;", page)  # no health check: Notion unknown
        self.assertIn("~1.0K · 100% of start", page)

    def test_the_projects_page_carries_the_baseline_and_honours_the_range(self):
        f = dashboard.Filters({"range": ["7"]})
        page = dashboard.page_projects(self.conn, f, {"p": [self.app_group()["id"]]}, "full")
        self.assertIn("Every new session starts at ~1.0K tokens", page)
        self.assertIn("median of 4 sessions", page)
        self.assertIn("<span class=\"\">1.0K</span>", dashboard.page_projects(self.conn, f, {}, "full"))


if __name__ == "__main__":
    unittest.main()
