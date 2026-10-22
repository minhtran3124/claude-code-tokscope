import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tokscope import dashboard, skills
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
        # history is 50 days: the 30 days before hold 20 days of data, so 2000/30 a day is set against 1000/20 a day
        self.assertIn('<span class="trend up">+33%</span>', body)
        self.assertEqual(body.count("Change = average per day in this range against the 20 days before it"), 1)

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
        self.assertIn('<a href="/library">Library<span class="cnt"', body)       # the name filter does not follow into the Library
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

    def add_hours(self, hours, tokens=100):
        """`tokens` every hour for `hours` hours back from now."""
        self.conn.executemany(
            "INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, cache_write_5m, "
            "cache_write_1h, cost_usd) VALUES ('s1',?,?,'claude-opus-5-5',1,?,0,0,0,0,0.1)",
            [(f"h{h}", (NOW - timedelta(hours=h, seconds=60)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), tokens) for h in range(hours)])

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
        for d in range(9):
            self.add(d, 1000 if d < 7 else 350)                            # the 2 days before the range hold less
        body = self.page({"range": ["7"]})
        self.assertEqual(body.count("Change = average per day in this range against the 1 day before it"), 1)
        self.assertIn('<span class="trend up">+43%</span>', body)         # 1000 a day against 700 in the one day of data before
        window = dashboard._window(self.conn, dashboard.Filters({"range": ["7"]}))
        self.assertEqual(window["now"], 7)
        self.assertAlmostEqual(window["before"], 1, places=2)

    def test_a_flat_history_of_7_6_days_shows_no_change_and_one_of_10_days_shows_none_too(self):
        self.add_hours(int(7.6 * 24))                                      # 7.6 days elapsed: over the gate, under a full day before
        body = self.page({"range": ["7"]})
        self.assertNotIn('class="dl"', body)
        self.assertNotIn("Change = average per day", body)
        self.assertIn("Less than a day of data before this range", body)
        self.conn.execute("DELETE FROM requests")
        self.add_hours(240)                                                # 10 days of the same 100 an hour
        body = self.page({"range": ["7"]})
        self.assertIn("against the 2 days before it", body)
        self.assertRegex(body, r'class="dl"><span class="trend \w+">[+-]?[0-2]%</span>')   # a flat input reads flat (hourly samples
        self.assertNotIn("+269%", body)                                                      # leave a rounding of a percent or two)

    def test_a_window_before_shorter_than_the_range_is_compared_per_day(self):
        self.add_hours(40 * 24)                                            # the same 100 an hour for 40 days
        body = self.page()                                                 # 30 days; only 9.96 days of data before them
        self.assertIn("against the 9 days before it", body)
        self.assertIn('<span class="trend flat">+0%</span>', body)         # not -67%, which 10 days over 30 would read as
        window = dashboard._window(self.conn, dashboard.Filters({}))
        self.assertEqual(window["now"], 30)
        self.assertAlmostEqual(window["before"], 9.96, places=1)

    def test_no_comparison_for_all_time_or_with_nothing_before_the_range(self):
        for d in range(20):
            self.add(d)
        self.assertIsNone(dashboard._window(self.conn, dashboard.Filters({"range": ["all"]})))
        self.assertIsNone(dashboard._window(self.conn, dashboard.Filters({})))        # 20 days of history, 30-day range
        body = self.page()
        self.assertNotIn("Change = average per day", body)
        self.assertNotIn("more than 7 days of history", body)                          # 20 days is more than 7: do not say otherwise
        self.assertIn("nothing to compare yet", body)
        self.assertIn("All time has no range before it", self.page({"range": ["all"]}))

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
        self.assertEqual(body.count('<div class="col">'), 2)               # no subagents: that column drops out
        self.assertNotIn("Subagent types", body)

    def test_top_spenders_columns_stay_level(self):
        for i, skill in enumerate(("a", "b", "c", "d")):
            self.add(1 + i, 100 * (i + 1), skill=skill)
        self.add(1, 50, agent="x1")                                        # one subagent type: the other columns show 2 rows
        body = self.page()
        self.assertEqual(body.count('<tr><td title="'), 0)
        self.assertEqual(len(re.findall(r"<tr><td", body.split('class="card spenders"')[1])), 4)   # 2 skills, 1 type, 1 session
        self.assertIn("at most 2 rows", body)

    def test_each_kpi_keeps_its_sparkline_and_the_header_and_sidebar_follow_the_design(self):
        for d in range(3):
            self.add(d)
        self.conn.execute("UPDATE requests SET output = 10, cache_read = 50, agent_id = 'a1', agent_type = 'Explore'")
        body = self.page({"range": ["7"]})
        self.assertEqual(body.count('class="spark"'), 6)
        for label in ("Range", "Project", "Model", "Skill"):
            self.assertIn(f"<label class=\"fl\"><span>{label}</span>", body)
        self.assertRegex(body, r'class="range-dates note">\d\d \w{3} \d{4} – \d\d \w{3} \d{4}<')
        self.assertIn('Sessions<span class="cnt" title="All time, not filtered">1</span></a>', body)
        self.assertIn('Projects<span class="cnt" title="All time, not filtered">1</span></a>', body)
        self.assertNotIn('class="privacy"', body)                           # the full level shows no chip
        redacted = dashboard.render(self.conn, "overview", {}, "stamp", level="redacted")
        self.assertIn('Sessions<span class="cnt"', redacted)
        for hidden in ("Projects", "Library", "Benchmarks"):               # pages the level hides carry no count
            self.assertRegex(redacted, rf'>{hidden}</a>')
        self.assertRegex(redacted, r'<h1>Overview</h1><span class="privacy" role="note"[^>]*><b>redacted</b></span>')

    def test_the_cause_is_main_thread_tokens_when_the_total_fell_and_no_skill_did(self):
        for d in range(40):                                                # before the range: 3000 a day, none of it a skill
            self.add(d, 3000 if d >= 30 else 1000)
        self.add(1, 100, skill="newcomer")                                 # the one mover rose while the total fell
        body = self.page()
        self.assertIn("Tokens per day fell", body)
        self.assertIn("mostly main-thread tokens that no skill or subagent type accounts for", body)
        self.assertNotIn("Biggest cause", body)

    def test_the_seven_day_average_counts_days_off_as_zero(self):
        rows = [("2026-10-01", 1000, 0.1, 1, 0, 0, 0, 1000), ("2026-10-07", 1000, 0.1, 1, 0, 0, 0, 1000)]
        svg = dashboard._daily_stacked(rows, [], [])
        self.assertEqual(svg.count('<g class="d"'), 7)                      # days off are empty slots
        last = re.search(r'class="ma"[^>]*points="([^"]+)"', svg).group(1).split()[-1]
        self.assertEqual(last.split(",")[1], f"{218 - 184 * (2000 / 7) / 1000:.1f}")  # 2000 over 7 calendar days, not 1000

    def test_the_y_axis_labels_the_gridlines_where_they_are(self):
        marks = {k: [0] * 25 for k in ("p25", "med", "p75")}
        marks["p75"] = [100] * 25
        svg = dashboard._today_chart({**marks, "n": 9}, [(0, 0)], 1.0, 100)
        self.assertIn(">105</text>", svg)                                   # top gridline = 1.05 x the largest value, labelled as such

    def test_local_hours_are_exact_in_a_half_hour_zone(self):
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Kolkata"
        time.tzset()
        self.addCleanup(lambda: (os.environ.pop("TZ", None) if old is None else os.environ.__setitem__("TZ", old), time.tzset()))
        day = (datetime.now(timezone.utc) - timedelta(days=3)).replace(hour=0, minute=30, second=0, microsecond=0)
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, cache_write_5m, "
                          "cache_write_1h, cost_usd) VALUES ('s1','tz',?,'claude-opus-5-5',1,500,0,0,0,0,0.1)", (day.strftime("%Y-%m-%dT%H:%M:%S.000Z"),))
        self.conn.commit()
        hours = dashboard._hours(self.conn, dashboard.Filters({}))
        local = day.astimezone()
        self.assertEqual((local.hour, local.minute), (6, 0))                # 00:30 UTC is 06:00 in Kolkata
        self.assertEqual(hours[local.date()][6], 500)
        self.assertEqual(sum(hours[local.date()]), 500)

    def test_sidebar_counts_are_cached_and_follow_the_folded_projects(self):
        self.conn.commit()
        with mock.patch.object(dashboard.library, "discover", return_value=[1, 2, 3]) as lib, \
                mock.patch.object(dashboard.projects, "discover", return_value=[{"root": "/a"}, {"root": "/b"}, {"root": None}]):
            dashboard._NAV_CACHE.clear()
            first = dashboard._nav_counts(self.conn)
            dashboard._nav_counts(self.conn)
        self.assertEqual((first["projects"], first["library"]), (2, 3))     # the Projects page's folded groups, benchmark rows left out
        self.assertEqual(lib.call_count, 1)                                 # the second render reads the cache
        self.assertEqual(set(dashboard._nav_counts(self.conn, "numbers")), {"sessions"})
