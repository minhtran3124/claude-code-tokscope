import re
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tokscope import dashboard, report, skills
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
        self.assertIn('data-set-skin="classic"', page)
        self.assertIn('data-set-theme="auto"', page)

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
        # history is 51 days: the 30 days before hold 21 days of data, so 2000/30 a day is set against 1000/21 a day
        self.assertIn('<span class="trend up">+40%</span>', body)
        self.assertEqual(body.count("Change = average per day in this range against the 21 days before it"), 1)

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
        self.assertIn('<a href="/library">Library<span class="cnt">', body)       # the name filter does not follow into the Library
        self.assertIn("catch(_){}", dashboard.LIB_JS)               # a malformed #v- hash leaves the rest of the script running

    def test_a_big_rise_reads_as_a_multiple(self):
        self.assertIn(">×25</span>", dashboard._delta(2500, 100))
        self.assertIn(">+900%</span>", dashboard._delta(1000, 100))
        self.assertEqual(dashboard._delta(5, 0), "")                      # nothing before: no chip, no note

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


class OverviewTest(unittest.TestCase):
    """The Overview answers from `requests` alone: deltas per day, a typical day, one container per group."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"TOKSCOPE_HOME": str(self.tmp / "home"), "HOME": str(self.tmp / "h")})
        env.start()
        self.addCleanup(env.stop)
        self.conn = connect(self.tmp / "t.db")
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s1','-home-u-app','/home/u/app','Work',1)")

    def add(self, days_ago, tokens=1000, agent=None, skill=None):
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, agent_id, agent_type, prompt_idx, skill, input, output, "
                          "cache_read, cache_write_5m, cache_write_1h, cost_usd) VALUES ('s1',?,?,'claude-opus-5-5',?,?,1,?,?,0,0,0,0,0.5)",
                          (f"k{days_ago}-{agent}-{skill}", self.ts(days_ago), agent, "Explore" if agent else None, skill, tokens))

    @staticmethod
    def ts(days_ago):
        """A minute older than the whole day, so a request never sits on the edge of a range."""
        return (NOW - timedelta(days=days_ago, seconds=60)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def page(self, qs=None):
        self.conn.commit()
        return dashboard.render(self.conn, "overview", qs or {}, "stamp")

    def test_no_deltas_and_no_note_with_7_days_of_history_or_fewer(self):
        for d in range(7):                                                  # today and the 6 days before: 7 days
            self.add(d)
        body = self.page({"range": ["7"]})
        self.assertNotIn('class="trend', body)
        self.assertNotIn("too short", body)
        self.assertNotIn("Change = average per day", body)
        self.assertIn("Biggest movers appear once there are more than 7 days of history", body)

    def test_deltas_show_with_8_days_of_history_and_say_once_what_they_compare(self):
        for d in range(8):
            self.add(d, 1000 if d < 7 else 700)                            # the one day before the range holds less
        body = self.page({"range": ["7"]})
        self.assertEqual(body.count("Change = average per day in this range against the 1 days before it"), 1)
        self.assertIn('<span class="trend up">+43%</span>', body)         # 1000 a day against 700 a day
        self.assertEqual(dashboard._window(self.conn, dashboard.Filters({"range": ["7"]})), {"now": 7, "before": 1})

    def test_phone_menu_is_a_button_for_a_sheet_with_the_pages_filters_controls_and_privacy_note(self):
        self.add(0)
        body = self.page({"project": ["-home-u-app"]})
        self.assertIn('id="menu-btn" aria-controls="sheet" aria-expanded="false"', body)
        sheet = body.split('<div class="sheet" id="sheet">', 1)[1].split("</aside>", 1)[0]
        self.assertIn('<nav class="toc"', sheet)                                   # the pages
        self.assertIn('class="filters sheet-filters"', sheet)                      # the same filter form
        self.assertIn("data-set-theme", sheet)                                      # the theme control
        self.assertIn("Privacy level:", sheet)
        self.assertIn("<span>Last 30 days · app</span>", body)                     # the filters as one pill
        self.assertIn('aria-controls="sheet" aria-expanded="false" aria-haspopup="dialog"', body)
        self.assertIn("e.key==='Escape'", dashboard.DASH_JS)                       # keyboard: Escape closes, Tab wraps, focus returns
        self.assertIn("main.inert=on", dashboard.DASH_JS)

    def test_pill_names_the_range_and_any_model_or_skill_and_the_library_only_the_project(self):
        f = dashboard.Filters({"range": ["7"], "model": ["claude-opus-5-5"], "skill": ["plan"]})
        self.assertEqual(dashboard._filter_pill(self.conn, f, "overview"), "Last 7 days · all projects · opus-5-5 · plan")
        self.assertEqual(dashboard._filter_pill(self.conn, f, "library"), "all projects")

    def test_daily_chart_has_a_phone_copy_of_14_days_with_4_labels(self):
        for d in range(30):
            self.add(d)
        body = self.page()
        wide, narrow = (re.search(rf'<svg class="{c}".*?</svg>', body, re.S).group(0) for c in ("wide", "narrow"))
        self.assertEqual(narrow.count('<g class="d"'), 14)
        self.assertEqual(wide.count('<g class="d"'), 30)
        labels = re.findall(r'<text x="[\d.]+" y="194" text-anchor="\w+">([\d-]+)</text>', narrow)
        self.assertEqual(len(labels), 4)

    def test_phone_section_is_in_the_layout_sheet_and_the_static_report_has_no_menu(self):
        from tokscope.layout import LAYOUT_DASH_CSS
        block = LAYOUT_DASH_CSS.split("/* phone */", 1)[1].split("/* end phone */", 1)[0]
        self.assertIn("@media (max-width:639px)", block)
        self.assertIn("min-height:44px", block)
        self.assertIn("prefers-reduced-motion:reduce", block)                      # the sheet fades, it does not travel
        self.assertNotIn("menu-btn", report.JS)
        self.assertIn(".spenders td:first-child a,.spenders td:first-child span{display:inline-flex;align-items:flex-end;", block)  # name sits on its numbers, no loose gap

    def test_phone_breakpoint_is_639_in_css_and_script_and_the_sheet_leaves_dialog_and_select_keys_alone(self):
        from tokscope.layout import LAYOUT_DASH_CSS
        from tokscope.classic import CLASSIC_DASH_CSS
        block = LAYOUT_DASH_CSS.split("/* phone */", 1)[1].split("/* end phone */", 1)[0]
        self.assertNotIn("max-width:640px", block)
        self.assertNotIn("max-width:640px", CLASSIC_DASH_CSS.split("/* end overview */", 1)[1])
        self.assertIn("matchMedia('(max-width:639px)')", dashboard.DASH_JS)
        keys = dashboard.DASH_JS.split("document.addEventListener('keydown',e=>{if(!sheet.classList.contains('open'))return;", 1)[1][:400]
        self.assertIn("dialog[open]", keys.split("if(e.key==='Escape')", 1)[0])    # the shortcuts dialog keeps Escape and Tab
        self.assertIn("selOpen", keys)                                             # an open select keeps its Escape

    def test_classic_phone_controls_get_an_outline_that_reads_3_to_1(self):
        from tokscope.classic import CLASSIC_DASH_CSS
        rule = CLASSIC_DASH_CSS.split("the new controls have no other cue", 1)[1]
        self.assertIn("body .menu-btn", rule)
        self.assertIn("border-color:var(--muted)", rule.split("}", 1)[0])
        self.assertIn("4.69:1", CLASSIC_DASH_CSS)                                  # the measured ratio, not 4.0

    def test_a_window_before_shorter_than_the_range_is_compared_per_day(self):
        for d in range(40):                                                 # the same 1000 a day for 40 days
            self.add(d)
        body = self.page()                                                  # 30 days; only 10 days of data before them
        self.assertIn("against the 10 days before it", body)
        self.assertIn('<span class="trend flat">+0%</span>', body)         # not -67%, which 10 days over 30 would read as
        self.assertEqual(dashboard._window(self.conn, dashboard.Filters({})), {"now": 30, "before": 10})

    def test_no_comparison_for_all_time_or_with_nothing_before_the_range(self):
        for d in range(20):
            self.add(d)
        self.assertIsNone(dashboard._window(self.conn, dashboard.Filters({"range": ["all"]})))
        self.assertIsNone(dashboard._window(self.conn, dashboard.Filters({})))        # 20 days of history, 30-day range
        self.assertNotIn("Change = average per day", self.page())

    def test_biggest_movers_name_the_main_cause_per_day(self):
        for d in range(40):
            self.add(d, 1000 if d >= 30 else 2000, skill="old-skill" if d >= 30 else "new-skill")
        body = self.page()
        self.assertIn("Biggest cause: <b>new-skill</b> (skill)", body)
        self.assertIn('<table class="movers">', body)
        self.assertIn('<td class="tagc"><span class="tag">skill</span></td>', body)

    def test_a_typical_day_is_the_median_of_the_last_14_active_days(self):
        day = lambda n: date(2026, 10, 1) + timedelta(days=n)             # noqa: E731
        hours = lambda at, v: [v if h == at else 0 for h in range(24)]    # noqa: E731
        history = {day(n): hours(9, 100 + n) for n in range(0, 40, 2)}    # active every second day: days off in between
        history[day(80)] = hours(9, 5000)                                  # today is not part of the baseline
        typ = dashboard.typical_day(history, day(80))
        self.assertEqual(typ["n"], 14)
        self.assertEqual(typ["med"][9], 0)                                 # before 09:00 nothing has happened
        self.assertEqual(typ["med"][10], 125)                            # days 12..38, step 2: values 112..138, the median of 14 is 125
        self.assertEqual(typ["med"][24], typ["med"][10])
        self.assertLess(typ["p25"][10], typ["med"][10])
        self.assertGreater(typ["p75"][10], typ["med"][10])
        self.assertEqual(dashboard._at_hour(typ["med"], 9.5), typ["med"][9] + (typ["med"][10] - typ["med"][9]) / 2)

    def test_a_typical_day_needs_more_than_7_active_days_not_calendar_days(self):
        day = lambda n: date(2026, 10, 1) + timedelta(days=n)             # noqa: E731
        hours = [10] + [0] * 23
        week = {day(n * 3): hours for n in range(7)}                       # 7 active days spread over 19 calendar days
        self.assertIsNone(dashboard.typical_day(week, day(30)))
        week[day(22)] = hours                                              # an 8th active day
        self.assertIsNotNone(dashboard.typical_day(week, day(30)))

    def test_the_overview_shows_the_typical_chart_only_with_enough_active_days(self):
        for d in range(1, 20, 3):                                          # 7 active days within 19 calendar days
            self.add(d)
        self.add(0)
        body = self.page()
        self.assertNotIn('class="tchart"', body)
        self.assertIn("A typical-day line appears once more than 7 days have activity (7 so far)", body)
        for d in (2, 3, 5):
            self.add(d)
        body = self.page()
        self.assertIn('class="tchart"', body)
        self.assertIn('class="tband"', body)
        self.assertRegex(body, r'class="trend (up|down|flat)">[^<]*</span>(?: about)? a typical day by \d\d:\d\d')

    def test_daily_tokens_stack_the_main_thread_and_the_subagents(self):
        self.add(1, 700)
        self.add(1, 300, agent="a1")
        body = self.page()
        self.assertIn('<rect class="m a"', body)                           # the subagent segment
        self.assertIn("main 700 · subagents 300", body)
        self.assertIn("Subagents</span>", body)

    def test_a_skill_version_change_gets_a_dashed_line_and_label(self):
        self.add(3)
        self.add(1)
        self.conn.executescript(skills.SCHEMA)
        self.conn.executemany("INSERT INTO skill_versions (skill, version, first_seen, source, label) VALUES (?,?,?,?,?)",
                              [("xia2", "aaaaaa111111", self.ts(5), "disk", None), ("xia2", "bbbbbb222222", self.ts(2), "disk", None)])
        body = self.page()
        self.assertIn('class="chg-l"', body)
        self.assertIn("xia2 bbbbbb", body)
        self.assertIn("Skill version changed", body)

    def test_top_spenders_are_one_container_with_three_columns(self):
        self.add(1, skill="xia2")
        body = self.page()
        self.assertEqual(body.count('class="card spenders"'), 1)
        self.assertEqual(body.count('<div class="col">'), 3)

    def test_each_kpi_keeps_its_sparkline_and_the_header_and_sidebar_follow_the_design(self):
        for d in range(3):
            self.add(d)
        self.conn.execute("UPDATE requests SET output = 10, cache_read = 50, agent_id = 'a1', agent_type = 'Explore'")
        body = self.page({"range": ["7"]})
        self.assertEqual(body.count('class="spark"'), 6)
        for label in ("Range", "Project", "Model", "Skill"):
            self.assertIn(f"<label class=\"fl\"><span>{label}</span>", body)
        self.assertRegex(body, r'class="range-dates note">\d\d \w{3} \d{4} – \d\d \w{3} \d{4}<')
        self.assertIn('Sessions<span class="cnt">1</span></a>', body)
        self.assertIn('Projects<span class="cnt">1</span></a>', body)
        self.assertNotIn('class="privacy"', body)                           # the full level shows no chip
        redacted = dashboard.render(self.conn, "overview", {}, "stamp", level="redacted")
        self.assertRegex(redacted, r'<h1>Overview</h1><span class="privacy" role="note"[^>]*><b>redacted</b></span>')
