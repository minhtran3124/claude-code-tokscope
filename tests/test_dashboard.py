import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tokscope import dashboard
from tokscope.ingest import connect
from tokscope.paths import PACKAGE

NOW = datetime.now(timezone.utc)


def ts(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FiltersTest(unittest.TestCase):
    def test_the_default_is_30_days_and_the_previous_range_is_the_30_before(self):
        f = dashboard.Filters({})
        cond, params = f.cond()
        self.assertIn("NOT LIKE '%tokscope%-bench-%'", cond)
        self.assertEqual(len(params), 1)
        prev_cond, prev = f.cond(1)
        self.assertIn("r.ts < ?", prev_cond)
        self.assertEqual(prev[1], params[0])          # the previous range ends where this one starts

    def test_project_model_and_skill_narrow_the_query_and_only_set_ones_reach_links(self):
        f = dashboard.Filters({"range": ["7"], "project": ["-home-u-app"], "skill": ["xia2"], "model": [""]})
        cond, params = f.cond()
        self.assertIn("s.project = ?", cond)
        self.assertIn("r.skill = ?", cond)
        self.assertNotIn("r.model", cond)
        self.assertEqual(f.query(), "range=7&project=-home-u-app&skill=xia2")
        self.assertEqual(dashboard.Filters({"range": ["999"]}).range, "30")
        self.assertIsNone(dashboard.Filters({"range": ["all"]}).days)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"TOKSCOPE_HOME": str(self.tmp / "home"), "HOME": str(self.tmp / "h")})
        env.start()
        self.addCleanup(env.stop)
        self.db = self.tmp / "t.db"
        conn = connect(self.db)
        conn.executemany("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES (?,?,?,?,1)",
                         [("now1", "-home-u-app", "/home/u/app", "Fresh work", ), ("old1", "-home-u-app", "/home/u/app", "Older work")])
        for sid, key, days, tokens, skill in (("now1", "a", 2, 2000, "xia2"), ("old1", "b", 50, 1000, "xia2")):
            conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, skill, input, output, cache_read, "
                         "cache_write_5m, cache_write_1h, cost_usd) VALUES (?,?,?,'claude-opus-5-5',1,?,?,0,0,0,0,1.0)",
                         (sid, key, ts(days), skill, tokens))
        conn.commit()
        conn.close()
        self.live = dashboard.Live(self.db, PACKAGE / "phases.json", 60, projects_dir=self.tmp / "projects")
        (self.tmp / "projects").mkdir()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.BaseHTTPRequestHandler)
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = dashboard.handler(self.db, self.live, self.port, "full")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Host": host} if host else {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_the_version_poll_makes_no_redacted_copy(self):
        self.server.RequestHandlerClass = dashboard.handler(self.db, self.live, self.port, "redacted")
        with mock.patch.object(dashboard.privacy, "redacted_copy", side_effect=AssertionError("copied")) as copy:
            code, body = self.get("/api/version")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"stamp": self.live.stamp})
        copy.assert_not_called()

    def test_every_page_renders_and_names_itself(self):
        for name, title in dashboard.PAGES.items():
            code, body = self.get(f"/{name}")
            self.assertEqual(code, 200, name)
            self.assertIn(f"<title>tokscope · {title}</title>", body)
            self.assertIn(f'href="/{name}" class=on aria-current=page', body)

    def test_pages_carry_both_skins_and_the_switch_button(self):
        _, page = self.get("/overview")
        self.assertIn('<style id="skin-ink">', page)
        self.assertIn('<style id="skin-classic" media="not all">', page)
        self.assertIn('id="skin"', page)

    def test_fonts_are_served_from_the_package_and_nothing_else_is(self):
        _, page = self.get("/overview")
        self.assertIn("url(/fonts/BeVietnamPro-400-latin.woff2)", page)
        self.assertNotIn("fonts.googleapis", page)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/fonts/BeVietnamPro-400-latin.woff2") as r:
            self.assertEqual((r.status, r.headers["Content-Type"]), (200, "font/woff2"))
            self.assertEqual(r.read()[:4], b"wOF2")
        for bad in ("/fonts/../cli.py", "/fonts/x.woff2", "/fonts/..%2Fcli.py"):
            self.assertEqual(self.get(bad)[0], 404, bad)

    def test_overview_compares_the_range_with_the_one_before(self):
        _, body = self.get("/overview")
        self.assertIn('data-key="tokens">2.0K', body)           # only the request 2 days ago is in the last 30
        self.assertIn('<span class="trend up">+100%</span> vs the 30 days before', body)

    def test_the_summary_api_follows_the_filters(self):
        _, body = self.get("/api/summary?range=all")
        self.assertEqual(json.loads(body)["tokens"], 3000)
        _, body = self.get("/api/summary?range=7&skill=other")
        self.assertEqual(json.loads(body)["tokens"], 0)

    def test_the_skills_page_follows_the_filters_and_has_an_apply_button(self):
        _, body = self.get("/skills?range=all")
        self.assertIn('<button type="submit" class="chip">Apply</button>', body)
        self.assertIn("xia2", body)
        _, body = self.get("/skills?range=all&skill=other")
        self.assertIn("No skill loads match these filters.", body)
        _, body = self.get("/skills?range=all&project=-home-u-none")
        self.assertIn("No skill loads match these filters.", body)

    def test_no_percentage_when_history_covers_less_than_half_the_range_before(self):
        _, body = self.get("/overview?range=7")                  # 7 days before: data starts 50 days ago, fine
        self.assertNotIn("too short to compare", body)
        conn = connect(self.db)
        conn.execute("DELETE FROM requests WHERE session_id = 'old1'")
        conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, "
                     "cache_write_5m, cache_write_1h, cost_usd) VALUES ('old1','c',?,'claude-opus-5-5',1,1,0,0,0,0,0.01)", (ts(33),))
        conn.commit()
        conn.close()
        _, body = self.get("/overview")                          # 3 of the 30 days before have data: no +199,900%
        self.assertIn(f"history starts {ts(33)[:10]}: too short to compare", body)
        self.assertNotIn('class="trend', body)

    def test_a_big_rise_reads_as_a_multiple(self):
        self.assertIn(">×25</span>", dashboard._delta(2500, 100, "x"))
        self.assertIn(">+900%</span>", dashboard._delta(1000, 100, "x"))

    def test_a_partial_render_is_the_regions_only(self):
        _, body = self.get("/overview?partial=1")
        self.assertNotIn("<html", body)
        for region in ("kpis", "today", "changed", "trend", "top"):
            self.assertIn(f'data-region="{region}"', body)

    def test_another_host_name_and_unknown_paths_are_refused(self):
        self.assertEqual(self.get("/overview", host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(self.get("/nope")[0], 404)
        self.assertEqual(self.get("/api/nope")[0], 404)

    def test_a_new_transcript_changes_the_stamp_the_pages_poll(self):
        before = json.loads(self.get("/api/version")[1])["stamp"]
        proj = self.tmp / "projects" / "-home-u-app"
        proj.mkdir()
        line = {"type": "assistant", "requestId": "r9", "timestamp": ts(0), "cwd": "/home/u/app",
                "message": {"id": "m9", "model": "claude-opus-5-5", "content": [], "usage": {"input_tokens": 5, "output_tokens": 1}}}
        (proj / "new1.jsonl").write_text(json.dumps(line) + "\n")
        self.live.tick()
        self.assertIsNone(self.live.error)
        self.assertNotEqual(json.loads(self.get("/api/version")[1])["stamp"], before)


class ScriptTest(unittest.TestCase):
    def test_every_page_script_parses(self):
        # a Python escape that lands in a JS string as a real newline breaks every script on the page
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        for name, js in {"report": dashboard.JS_CORE + dashboard.JS_SESSIONS + dashboard.JS_TREND + dashboard.JS_BENCH,
                         "dashboard": dashboard.DASH_JS, "library": dashboard.LIB_JS}.items():
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
            run = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
            os.unlink(f.name)
            self.assertEqual(run.returncode, 0, f"{name}: {run.stderr[-400:]}")

    def test_pages_ask_for_new_data_every_2_seconds(self):
        # the "New data · reload" button and the live numbers wait at most this long after an ingest
        self.assertIn("setInterval(poll,2000)", dashboard.DASH_JS)

    def test_the_from_label_links_only_where_the_dashboard_serves_sessions(self):
        js = dashboard.JS_SESSIONS
        # an orphan child links to its parent's full id, all time; the id is URL-encoded and the name escaped
        self.assertIn("DASH&&s.parent?`<a href=\"/sessions?range=all&amp;q=${encodeURIComponent(s.parent)}\"", js)
        self.assertIn("${esc(by)}</a>`:esc(by)", js)
        # the static report's body has no data-page, so it keeps plain text
        self.assertIn("const DASH=!!document.body.dataset.page", js)

    def test_a_parent_with_many_children_can_collapse_again(self):
        js = dashboard.JS_SESSIONS
        self.assertIn("'Show fewer'", js)
        self.assertIn("setAttribute('aria-expanded'", js)
        self.assertIn("openKids.delete(id)", js)


class SkinSwitchReportTest(unittest.TestCase):
    def test_a_report_carries_both_skins_and_the_switch_button(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "t.db"
            connect(db).close()
            out = Path(d) / "r.html"
            from tokscope.report import write_report
            write_report(db, out, tasks_dir=Path(d))
            page = out.read_text()
        self.assertIn('<style id="skin-ink">', page)
        self.assertIn('<style id="skin-classic" media="not all">', page)
        self.assertIn('id="skin"', page)

    def test_classic_nests_child_sessions_like_ink(self):
        from tokscope.classic import CLASSIC_CSS
        for rule in (".srow.child{", ".srow.child::before{", ".btn.kids-more{", ".srow.orphan>summary .t{",
                     ".srow>summary .from{", ".srow.dim:not(:hover)"):
            self.assertIn(rule, CLASSIC_CSS)


if __name__ == "__main__":
    unittest.main()
