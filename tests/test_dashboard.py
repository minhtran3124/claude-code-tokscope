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

    def test_old_skills_links_land_on_the_library(self):
        class NoFollow(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_):
                return None
        opener = urllib.request.build_opener(NoFollow)
        for path, to in (("/skills", "/library"), ("/skills?project=-home-u-app&skill=xia2", "/library?project=-home-u-app")):
            with self.assertRaises(urllib.error.HTTPError) as e:
                opener.open(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual((e.exception.code, e.exception.headers["Location"]), (302, to))
        self.assertNotIn('href="/skills', self.get("/overview")[1])

    def test_the_library_filters_by_project_only(self):
        _, body = self.get("/library?project=-home-u-app")
        self.assertIn('<option value="-home-u-app" selected>app</option>', body)
        self.assertNotIn('name="range"', body)
        self.assertIn('<button type="submit" class="chip">Apply</button>', body)
        _, body = self.get("/library?skill=xia2")                  # a skill name, not an id: the list, with the bar
        self.assertIn('<form class="filters"', body)
        _, body = self.get("/overview?skill=xia2")
        self.assertIn('<a href="/library">Library</a>', body)       # the name filter does not follow into the Library
        self.assertIn("catch(_){}", dashboard.LIB_JS)               # a malformed #v- hash leaves the rest of the script running

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

    def test_sessions_page_has_a_sort_control_and_a_compare_tray(self):
        status, page = self.get("/sessions?range=all")
        self.assertEqual(status, 200)
        self.assertNotIn('<select id="s-sort"', page)
        for key, label in (("recent", "Newest"), ("tokens", "Most tokens"), ("agents", "Most subagent")):
            self.assertIn(f'data-sort="{key}"', page)
            self.assertIn(f">{label}</button>", page)
        self.assertIn('class="chip on" data-sort="recent" aria-pressed="true"', page)    # Newest is the start state
        self.assertIn('id="pickbar"', page)
        self.assertIn('id="session-list"', page)


class SessionsTableTest(unittest.TestCase):
    def test_the_table_groups_by_day_and_sizes_the_bar_by_tokens(self):
        js = dashboard.JS_SESSIONS
        self.assertIn("function dayEl(", js)                       # a header per day: its sessions and tokens
        self.assertIn("session${n===1?'':'s'} · ${fmt(tk)} tokens", js)
        self.assertIn("const MAXT=Math.max(...S.map(s=>s.tokens),1)", js)    # the bar is tokens against the largest in the list
        self.assertIn("100*(main+ag)/MAXT", js)
        self.assertIn("<u class=a", js)                            # the colours still split main thread and subagents
        head = js.split("function headEl", 1)[1].split("function dayEl", 1)[0]
        for col in ("time", "session", "top skill", "prompts", "children", "tokens", "split"):
            self.assertIn(f">{col}</span>", head)

    def test_sort_is_three_buttons_and_the_tray_shows_from_two_picks(self):
        js = dashboard.JS_SESSIONS
        for key in ("recent", "tokens", "agents"):
            self.assertIn(f"{key}:[", js)
        self.assertNotIn("sortSel", js)
        self.assertIn("`${n} of 4 picked`", js)                    # "2 of 4 picked"
        self.assertIn("pickBar.classList.toggle('show',on)", js)
        self.assertIn("const n=picked.size,on=n>=2", js)

    def test_the_table_script_has_no_literal_durations(self):
        import re
        js = dashboard.JS_SESSIONS
        self.assertIn("cssVar('--t-layout')", js)
        self.assertIsNone(re.search(r"duration:\s*\d", js))
        self.assertIsNone(re.search(r"easing:'ease", js))

    def test_rows_are_44px_and_children_keep_their_indent_in_the_layout_sheet(self):
        from tokscope.layout import LAYOUT_CSS
        block = LAYOUT_CSS.split("/* sessions:", 1)[1].split("/* end sessions */", 1)[0]
        self.assertIn("#session-list .srow>summary{height:44px", block)
        self.assertIn("padding-left:calc(var(--depth,0)*20px)", block)       # --depth is set per row by the script
        self.assertIn("#session-list .srow.child{margin-left:0}", block)
        self.assertIn("#sessions .pickbar.show{opacity:1", block)
        self.assertIn("calc(var(--t-state)*.7) var(--ease-exit)", block)    # the tray sinks at 0.7 of its entrance
        self.assertIn("@media (prefers-reduced-motion:reduce){#sessions .pickbar,#sessions .pickbar.show{transform:none}}", block)
        self.assertNotIn(".srow:hover>summary .split{transform", LAYOUT_CSS)    # no hover lift on a row's bar

    def test_each_skin_adds_only_the_look(self):
        from tokscope.classic import CLASSIC_CSS
        from tokscope.report import CSS
        ink = CSS.split("/* sessions look */", 1)[1].split("/* end sessions look */", 1)[0]
        classic = CLASSIC_CSS.split("/* sessions look */", 1)[1].split("/* end sessions look */", 1)[0]
        self.assertIn("#session-list{border:var(--line-w) solid var(--ink);border-radius:12px", ink)
        self.assertIn("text-transform:uppercase", ink)
        self.assertIn("border-radius:999px", ink)                  # the Ink tray is a filled ink pill
        self.assertIn("#session-list{border:1px solid var(--edge);border-radius:8px", classic)
        self.assertNotIn("uppercase", classic)
        self.assertIn("box-shadow:0 10px 30px -12px", classic)     # the Classic tray: tinted, soft shadow

    def test_the_static_report_gets_the_same_sort_control(self):
        from tokscope.report import write_report
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "t.db"
            connect(db).close()
            out = Path(d) / "r.html"
            write_report(db, out, tasks_dir=Path(d))
            page = out.read_text()
        self.assertIn('data-sort="agents"', page)
        self.assertIn('id="pickbar"', page)


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

    def test_one_layout_sheet_comes_before_both_skins(self):
        from tokscope.classic import CLASSIC_CSS
        from tokscope.layout import LAYOUT_CSS
        from tokscope.report import CSS, write_report
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "t.db"
            connect(db).close()
            out = Path(d) / "r.html"
            write_report(db, out, tasks_dir=Path(d))
            page = out.read_text()
        self.assertLess(page.index('<style id="layout">'), page.index('<style id="skin-ink">'))
        self.assertEqual(page.count('<style id="layout">'), 1)
        rule = ".changes{display:grid;"
        self.assertIn(rule, LAYOUT_CSS)                   # a rule both skins share is written once, not in each skin
        self.assertNotIn(rule, CSS)
        self.assertNotIn(rule, CLASSIC_CSS)

    def test_classic_nests_child_sessions_like_ink(self):
        from tokscope.classic import CLASSIC_CSS, CLASSIC_DASH_CSS
        from tokscope.layout import LAYOUT_CSS, LAYOUT_DASH_CSS
        classic_sheets = LAYOUT_CSS + LAYOUT_DASH_CSS + CLASSIC_CSS + CLASSIC_DASH_CSS    # the sheets a Classic page applies
        for rule in (".srow.child{", ".srow.child::before{", ".btn.kids-more{", ".srow.orphan>summary .t{",
                     ".srow>summary .from{", ".srow.dim:not(:hover)"):
            self.assertIn(rule, classic_sheets)


if __name__ == "__main__":
    unittest.main()
