import re
import json
import os
import sys
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

from tokscope.core import skills, summary
from tokscope.integrations import managed
from tokscope.web import dashboard
from tokscope.web.report import scripts as report_scripts
from http.server import BaseHTTPRequestHandler
from tokscope.core import privacy as core_privacy
from tokscope.features import library as features_library
from tokscope.features import projects as features_projects
from tokscope.web.dashboard import shell
from tokscope.web.dashboard.pages import overview as overview_page
from tokscope.web.report.scripts import JS_BENCH
from tokscope.web.report.scripts import JS_CORE
from tokscope.web.report.scripts import JS_SESSIONS
from tokscope.web.report.scripts import JS_TREND
from tokscope.core.ingest import connect
from tokscope.paths import ASSETS

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
        ant = mock.patch.object(managed, "_run", side_effect=RuntimeError("ant is not run in tests"))  # the Managed page
        ant.start()
        self.addCleanup(ant.stop)
        self.addCleanup(managed.forget)
        self.claude = self.tmp / "claude"  # open sessions come from <config dir>/sessions, never the real one
        (self.claude / "sessions").mkdir(parents=True)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.claude)})
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.live = dashboard.Live(self.db, ASSETS / "phases.json", 60, projects_dir=self.tmp / "projects")
        (self.tmp / "projects").mkdir()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = dashboard.handler(self.db, self.live, self.port, "full")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_the_version_poll_has_the_keys_the_desktop_app_checks(self):
        # desktop/main.js isTokscope() takes an answer with "stamp" and "live" for a tokscope dashboard
        self.assertTrue({"stamp", "live"} <= set(json.loads(self.get("/api/version")[1])))

    def test_a_failed_ingest_shows_in_the_version_poll_and_the_page_script(self):
        self.live.error = "database is locked"
        self.assertEqual(json.loads(self.get("/api/version")[1])["error"], "database is locked")
        self.assertIn("last ingest failed", dashboard.scripts.DASH_JS)

    def get(self, path, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Host": host} if host else {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_the_version_poll_makes_no_redacted_copy(self):
        self.server.RequestHandlerClass = dashboard.handler(self.db, self.live, self.port, "redacted")
        with mock.patch.object(core_privacy, "redacted_copy", side_effect=AssertionError("copied")) as copy:
            code, body = self.get("/api/version")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"stamp": self.live.stamp, "error": None, "live": ""})
        copy.assert_not_called()

    def open_session(self, pid, sid, status="busy", entrypoint="cli"):
        (self.claude / "sessions" / f"{pid}.json").write_text(json.dumps(
            {"pid": pid, "sessionId": sid, "status": status, "entrypoint": entrypoint}))

    def test_open_sessions_show_on_the_live_endpoint_and_the_overview_and_dead_pids_do_not(self):
        self.open_session(os.getpid(), "now1-aaaa", "busy")
        self.open_session(os.getppid(), "old1-bbbb", "idle", "claude-vscode")
        (self.claude / "sessions" / "2.json").write_text(json.dumps({"pid": 2 ** 22 + 12345, "sessionId": "dead", "status": "busy"}))
        (self.claude / "sessions" / "3.json").write_text("{half")
        code, body = self.get("/api/live")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"now1-aaaa": {"status": "busy", "entry": "Terminal"},
                                            "old1-bbbb": {"status": "idle", "entry": "VS Code"}})
        _, over = self.get("/overview")
        self.assertRegex(over, r'data-region="running"><p class="runnow"><span class="dot live busy-now"></span><b data-count="2"')
        self.assertIn("1 working · 1 waiting for you", over)
        self.assertIn("VS Code", over)
        self.assertNotIn("dead", over)
        self.assertNotEqual(json.loads(self.get("/api/version")[1])["live"], "")

    def test_the_today_heading_and_the_running_line_share_one_row(self):
        from tokscope.web.theme.layout import LAYOUT_CSS, LAYOUT_DASH_CSS
        self.open_session(os.getpid(), "now1-aaaa", "busy")
        self.assertRegex(self.get("/overview")[1], r'<div class="live-head">\s*<h2><span class="dot"></span>Today</h2>\s*<div data-region="running">\s*<p class="runnow">.*?</p>\s*</div>\s*</div>\s*<div data-region="today">', re.S)
        self.assertRegex(self.get("/overview")[1], r'</b> <span class="lbl">sessions? running</span><span class="note">')
        (self.claude / "sessions" / f"{os.getpid()}.json").unlink()
        self.assertRegex(self.get("/overview")[1], r'<div class="live-head">\s*<h2>.*?Today</h2>\s*<div data-region="running">\s*<p class="runnow none">', re.S)
        css = LAYOUT_CSS + LAYOUT_DASH_CSS
        self.assertRegex(css, r"\.live-head\{[^}]*display:flex[^}]*flex-wrap:wrap")
        # the region may shrink, so a long note wraps inside it instead of pushing the line under the heading
        self.assertRegex(css, r"\.live-head \[data-region=running\]\{[^}]*flex:1 1[^}]*min-width:0")
        # one line: the heading's dot sits on the text baseline (not centred, which moved the h2 baseline), as do the
        # running line's items, and the running dot is no longer centred on the taller count
        self.assertRegex(css, r"\.live-head>h2\{[^}]*align-items:baseline")
        self.assertRegex(css, r"\.runnow\{[^}]*display:grid[^}]*grid-template-columns:auto auto minmax\(0,1fr\)[^}]*align-items:baseline")
        # the note sits in the label column, so its left edge follows the label for any count width and for "session"
        self.assertRegex(css, r"\.runnow \.note\{[^}]*grid-column:3")
        self.assertNotRegex(css, r"\.runnow \.dot\{[^}]*align-self:center")

    def test_the_overview_says_so_when_nothing_is_open(self):
        _, over = self.get("/overview")
        self.assertIn("No Claude Code session is open", over)
        self.assertNotIn('class="dot live', over)

    def test_the_sessions_page_tags_open_rows_from_the_live_endpoint(self):
        _, page = self.get("/sessions")
        self.assertIn("/api/live", page)
        self.assertIn("liveTag", page)

    def test_every_page_renders_and_names_itself(self):
        for name, title in dashboard.PAGES.items():
            code, body = self.get(f"/{name}")
            self.assertEqual(code, 200, name)
            self.assertIn(f"<title>tokscope · {title}</title>", body)
            self.assertIn(f'href="/{name}" class=on aria-current=page', body)

    def test_managed_refresh_reads_again_and_drops_the_query(self):
        managed._cache["all"] = (1e18, {"error": "old", "read_at": 0})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/managed?refresh=1")
        opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a: None}))
        with self.assertRaises(urllib.error.HTTPError) as e:
            opener.open(req)
        self.assertEqual((e.exception.code, e.exception.headers["Location"]), (302, "/managed"))
        self.assertEqual(managed._cache, {})
        code, body = self.get("/managed")                                 # where the redirect lands: a fresh read
        self.assertEqual(code, 200)
        self.assertIn("ant is not run in tests", body)
        self.assertEqual(managed._cache["all"][1]["error"], "ant is not run in tests")
        with self.assertRaises(urllib.error.HTTPError) as e:                # an agent's view keeps its agent
            opener.open(urllib.request.Request(f"http://127.0.0.1:{self.port}/managed?refresh=1&agent=agent_01%2FA"))
        self.assertEqual(e.exception.headers["Location"], "/managed?agent=agent_01%2FA")

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

    def test_rows_in_json_and_csv_follow_the_filters(self):
        code, body = self.get("/api/summary?by=skill&format=json&range=all")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), [{"key": "xia2", "requests": 2, "prompt_tokens": 3000, "output_tokens": 0, "cost_usd": 2.0,
                                             "carried_cost_usd": 0.0}])
        _, body = self.get("/api/summary?by=skill&format=json&range=7")
        self.assertEqual([r["requests"] for r in json.loads(body)], [1])  # the 50-day-old request is out
        code, body = self.get("/api/summary?by=model&format=csv&range=all&skill=nothing")
        self.assertEqual((code, body), (200, ",".join(summary.FIELDS) + "\n"))

    def test_bad_values_are_refused_and_the_old_totals_stay(self):
        for q in ("by=nope", "format=xml", "by=skill&limit=x"):
            self.assertEqual(self.get("/api/summary?" + q)[0], 400, q)
        self.assertEqual(json.loads(self.get("/api/summary?range=all")[1])["tokens"], 3000)

    def test_other_hosts_are_refused(self):
        self.assertEqual(self.get("/api/summary?by=skill&format=csv", host="evil.example:80")[0], 403)

    def test_the_breakdowns_page_has_the_summary_with_links_for_the_filters(self):
        _, body = self.get("/breakdowns?range=7&by=skill&model=claude-opus-5-5")
        self.assertIn('id="summary"', body)
        self.assertIn('href="/api/summary?range=7&amp;model=claude-opus-5-5&amp;by=skill&amp;format=csv"', body)
        self.assertIn('href="/api/summary?range=7&amp;model=claude-opus-5-5&amp;by=skill&amp;format=json"', body)
        self.assertIn('class="chip on" href="/breakdowns?range=7&amp;model=claude-opus-5-5&amp;by=skill#summary" aria-current=page>Skill', body)
        self.assertIn("data-copy", body)
        self.assertIn('data-by="skill"', body)
        self.assertNotIn('data-by="phase"', body)

    def test_an_unknown_group_by_falls_back_to_phase(self):
        self.assertIn('data-by="phase"', self.get("/breakdowns?by=zzz")[1])

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
        self.assertIn(">×25</span>", overview_page._delta(2500, 100))
        self.assertIn(">+900%</span>", overview_page._delta(1000, 100))
        self.assertEqual(overview_page._delta(5, 0), "")                      # nothing before: no chip, no note

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
        js = JS_SESSIONS
        self.assertIn("function dayEl(", js)                       # a header per day: its sessions and tokens
        self.assertIn("session${n===1?'':'s'} · ${fmt(tk)} tokens", js)
        self.assertIn("const MAXT=Math.max(...S.map(s=>s.tokens),1)", js)    # the bar is tokens against the largest in the list
        self.assertIn("100*(main+ag)/MAXT", js)
        self.assertIn("<u class=a", js)                            # the colours still split main thread and subagents
        head = js.split("function headEl", 1)[1].split("function dayEl", 1)[0]
        for col in ("time", "session", "top skill", "prompts", "subagents", "tokens", "split"):
            self.assertIn(f">{col}</span>", head)

    def test_sort_is_three_buttons_and_the_tray_shows_from_two_picks(self):
        js = JS_SESSIONS
        for key in ("recent", "tokens", "agents"):
            self.assertIn(f"{key}:[", js)
        self.assertNotIn("sortSel", js)
        self.assertIn("${n} of 4 picked", js)                      # "2 of 4 picked"
        self.assertIn("pickBar.classList.toggle('show',on)", js)
        self.assertIn("const n=picked.size,on=n>=2", js)

    def test_the_table_script_has_no_literal_durations(self):
        import re
        js = JS_SESSIONS
        self.assertIn("cssVar('--t-layout')", js)
        self.assertIsNone(re.search(r"duration:\s*\d", js))
        self.assertIsNone(re.search(r"easing:'ease", js))

    def test_an_opened_session_is_one_tinted_panel_in_every_skin(self):
        from tokscope.web.theme.layout import LAYOUT_CSS
        from tokscope.web.theme.classic import CLASSIC_CSS
        from tokscope.web.report.styles import CSS
        block = LAYOUT_CSS.split("/* sessions:", 1)[1].split("/* end sessions */", 1)[0]
        rule = re.search(r"#session-list \.srow\[open\],#session-list \.srow\[open\]:hover\{([^}]*)\}", block)
        self.assertIsNotNone(rule)                                            # the summary and the body are one element, so one rule
        self.assertIn("background:var(--tint)", rule.group(1))
        self.assertIn("inset 4px 0 0 var(--mark)", rule.group(1))
        self.assertNotRegex(rule.group(1), r"#[0-9a-fA-F]{3,8}\b")             # theme tokens only, no raw colour
        # one place defines the open-row look: no rule outside the layout sheet's panel rules styles an [open] row's ground
        for name, sheet in (("classic", CLASSIC_CSS), ("ink", CSS), ("layout", LAYOUT_CSS.replace(block, ""))):
            for sel, body in re.findall(r"([^{}]*\.srow[^{},]*\[open\][^{}]*)\{([^}]*)\}", sheet):
                self.assertNotRegex(body, r"(?:^|;)\s*(?:background|box-shadow|border-color)\s*:", f"{name}: {sel.strip()}")
        # opened and picked: explicit selectors (1,3,0 and 1,4,0) so hover and the skins' .picked rule lose in any file order
        picked = re.search(r"#session-list \.srow\.picked\[open\],#session-list \.srow\.picked\[open\]:hover\{([^}]*)\}", block)
        self.assertIsNotNone(picked)
        self.assertIn("inset 6px 0 0 var(--mark)", picked.group(1))        # a wider edge than the plain panel's 4px
        self.assertIn("var(--tint)", picked.group(1))
        self.assertNotRegex(picked.group(1), r"#[0-9a-fA-F]{3,8}\b")
        self.assertLess(block.index(rule.group(0)), block.index(picked.group(0)))
        for sheet in (CSS, CLASSIC_CSS):
            self.assertIn("--tint:", sheet)

    def test_rows_are_44px_and_children_keep_their_indent_in_the_layout_sheet(self):
        from tokscope.web.theme.layout import LAYOUT_CSS
        block = LAYOUT_CSS.split("/* sessions:", 1)[1].split("/* end sessions */", 1)[0]
        self.assertIn("#session-list .srow>summary{height:44px", block)
        self.assertIn("padding-left:calc(var(--depth,0)*20px)", block)       # --depth is set per row by the script
        self.assertIn("#session-list .srow.child{margin-left:0}", block)
        self.assertIn("#sessions .pickbar.show{opacity:1", block)
        self.assertIn("calc(var(--t-state)*.7) var(--ease-exit)", block)    # the tray sinks at 0.7 of its entrance
        self.assertIn("@media (prefers-reduced-motion:reduce){#sessions .pickbar,#sessions .pickbar.show{transform:none}}", block)
        self.assertNotIn(".srow:hover>summary .split{transform", LAYOUT_CSS)    # no hover lift on a row's bar

    def test_each_skin_adds_only_the_look(self):
        from tokscope.web.theme.classic import CLASSIC_CSS, CLASSIC_DASH_CSS
        from tokscope.web.theme.layout import LAYOUT_TOKEN_CSS, LAYOUT_TOKEN_DASH_CSS
        from tokscope.web.report.styles import CSS
        layout = LAYOUT_TOKEN_CSS + LAYOUT_TOKEN_DASH_CSS
        # the outline, radius and label case are tokens read once in the layout sheet
        self.assertIn("#session-list{border:var(--line-w) solid var(--line-c);border-radius:var(--r-box)", layout)
        self.assertIn("text-transform:var(--lab-case)", layout)
        self.assertIn("--lab-case:uppercase", CSS)
        self.assertIn("--lab-case:none", CLASSIC_CSS)
        self.assertIn("border-radius:999px", CSS + dashboard.DASH_CSS)  # the Ink tray is a filled ink pill
        self.assertNotIn("uppercase", CLASSIC_DASH_CSS)
        self.assertIn("box-shadow:0 10px 30px -12px", CLASSIC_CSS)     # the Classic tray: tinted, soft shadow

    def test_a_hostile_session_id_is_escaped_everywhere_the_script_writes_html(self):
        js = JS_SESSIONS
        self.assertIn("<code class=sid8>${esc(s.id.slice(0,8))}</code>", js)
        self.assertIn("${esc(s.id.slice(0,8))}</span></th>", js)               # the compare header
        self.assertIn("<span class=d>${esc(when(s))}</span>", js)

    def test_hostile_session_id_reaches_the_page_only_as_json_data(self):
        from tokscope.web.report.sections.sessions import _sessions_json
        with tempfile.TemporaryDirectory() as d:
            conn = connect(Path(d) / "t.db")
            bad = "<img src=x onerror=alert(1)>"
            conn.execute("INSERT INTO sessions (session_id, project, title, prompts) VALUES (?, 'p', 't', 1)", (bad,))
            conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, cache_write_5m, "
                         "cache_write_1h, cost_usd) VALUES (?, 'a', ?, 'm', 1, 5, 0, 0, 0, 0, 0)", (bad, ts(1)))
            conn.commit()
            page = dashboard.page_sessions(conn, dashboard.Filters({"range": ["all"]}), {})
        markup, _, data = page.partition('<script type="application/json"')
        self.assertNotIn("<img src=x", markup)                     # the id is only in the inert JSON block
        self.assertNotIn("</", data.split(">", 1)[1].rsplit("</script>", 1)[0])    # and "</" cannot close that block
        self.assertEqual(_sessions_json(conn, "WHERE 1", ())[0]["id"], bad)    # it stays data; esc() in the script makes it text

    def test_labels_say_subagents_not_children_and_a_session_without_a_date_is_handled(self):
        js = JS_SESSIONS
        head = js.split("function headEl", 1)[1].split("function dayEl", 1)[0]
        self.assertNotIn("children", head)
        self.assertIn("subagent runs", js)
        self.assertIn("!d?'No date'", js)
        self.assertIn("let cur=null", js)                          # a first day with no start still gets its header
        self.assertIn("!a[0].s.start-!b[0].s.start", js)           # undated sessions sort last
        self.assertNotIn("aria-hidden','true'", head)              # the column names are for screen readers too
        self.assertIn("the 5th is blocked", js)
        self.assertNotIn("#060", js)

    def test_a_narrow_page_keeps_the_from_link_and_the_title_column(self):
        from tokscope.web.theme.layout import LAYOUT_CSS, LAYOUT_DASH_CSS
        block = (LAYOUT_CSS + LAYOUT_DASH_CSS).split("/* sessions:", 1)[1].split("/* end sessions */", 1)[0]
        self.assertIn("#session-list :is(.n,.sid8){display:none}", LAYOUT_CSS)       # the phone rows drop these, not the parent link
        self.assertNotIn(":is(.n,.sid8,.from)", LAYOUT_CSS)
        self.assertIn(".srow>summary .from{max-width:45%}", LAYOUT_CSS)
        self.assertIn("@media (max-width:1200px)", block)
        self.assertIn("@media (max-width:1040px)", block)

    def test_the_static_report_gets_the_same_sort_control(self):
        from tokscope.web.report import write_report
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
        for name, js in {"report": JS_CORE + JS_SESSIONS + JS_TREND + JS_BENCH,
                         "dashboard": dashboard.DASH_JS, "library": dashboard.LIB_JS}.items():
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
            run = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
            os.unlink(f.name)
            self.assertEqual(run.returncode, 0, f"{name}: {run.stderr[-400:]}")

    def test_the_folder_filter_matches_what_the_owner_typed(self):
        # runs the page's own matcher in node: ran in the folder, ran `claude -p` in it, or a prompt names it
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        code = "const base=" + JS_SESSIONS.split("const base=", 1)[1].split("function render(){", 1)[0] + r"""
const S=[{id:'a1',title:'Add export',top_skill:'review',cwd:'/home/x/projects/Travel-Pi/app',project:'app',turns:[]},
 {id:'b2',title:'Collect',cwd:'/home/x/other',project:'other',hdirs:['/home/x/projects/travel-pi'],turns:[]},
 {id:'c3',title:'Budget',cwd:'/home/x/other',project:'other',turns:[{text:'plan the travel-pi trip'}]},
 {id:'d4',title:'Redacted',cwd:'/project-ab12cd',project:'project-ab12cd',turns:[{text:'[prompt \u00b7 20 chars]'}]},
 {id:'e5',title:'No cwd',cwd:'',project:'',turns:[]},
 {id:'f6',title:'Travel-pi notes',cwd:'/x',project:'x',turns:[]}];
const out=n=>{const f=finder(n);return S.map(s=>[f.match(s)?1:0,f.whyOf(s)])};
console.log(JSON.stringify({pi:out('travel-pi'),prompt:out('prompt'),title:out('add'),id:out('b2'),skill:out('revie'),none:out('')}))"""
        run = subprocess.run([node, "-e", code], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr[-400:])
        got = json.loads(run.stdout)
        # a title match (f6) or a folder or prompt match (a1, b2, c3) keeps the row; only a non-title match gets a chip
        self.assertEqual(got["pi"], [[1, "in Travel-Pi"], [1, "ran claude -p in travel-pi"], [1, "mentions travel-pi"], [0, ""], [0, ""], [1, ""]])
        self.assertEqual([m for m, _ in got["prompt"]], [0, 0, 0, 0, 0, 0])      # a redaction placeholder is not text to search
        self.assertEqual([r for r in got["title"]], [[1, ""], [0, ""], [0, ""], [0, ""], [0, ""], [0, ""]])
        self.assertEqual([m for m, _ in got["id"]], [0, 1, 0, 0, 0, 0])           # an id prefix still matches, with no chip
        self.assertEqual([m for m, _ in got["skill"]], [1, 0, 0, 0, 0, 0])        # so does the top skill
        self.assertEqual(got["none"], [[1, ""]] * 6)                              # no needle keeps every row, no chip
        # render() trims the box once, so a pasted trailing space finds the folder and the chip text has none
        self.assertIn("finder(q.value.trim().toLowerCase())", JS_SESSIONS)
        trimmed = subprocess.run([node, "-e", "const q={value:'travel-pi  '};" + code.rsplit("const out=", 1)[0] +
                                  "const f=finder(q.value.trim().toLowerCase());console.log(JSON.stringify(S.map(s=>[f.match(s)?1:0,f.whyOf(s)])))"],
                                 capture_output=True, text=True)
        self.assertEqual(trimmed.returncode, 0, trimmed.stderr[-400:])
        self.assertEqual(json.loads(trimmed.stdout), got["pi"])

        # a session edited in place is searched by its new text, and the cache adds nothing to the data
        edit = subprocess.run([node, "-e", code.rsplit("const out=", 1)[0] + r"""
const a=finder('zebra'),before=a.match(S[0]);S[0].title='A zebra title';
const after=finder('zebra').match(S[0]),old=finder('add export').match(S[0]);
S[2].turns.push({text:'now about zebra crossings'});const turn=finder('crossings');
console.log(JSON.stringify([before,after,old,turn.match(S[2]),turn.whyOf(S[2]),JSON.stringify(S[0]).includes('_lc')]))"""],
                              capture_output=True, text=True)
        self.assertEqual(edit.returncode, 0, edit.stderr[-400:])
        self.assertEqual(json.loads(edit.stdout), [False, True, False, True, "mentions crossings", False])

    def test_the_reason_chip_wraps_only_the_rows_that_show_it_and_the_report_has_the_phone_list(self):
        from tokscope.web.theme.layout import LAYOUT_CSS, LAYOUT_DASH_CSS, LAYOUT_TOKEN_CSS
        self.assertEqual(LAYOUT_TOKEN_CSS.count(".srow>summary .why{"), 1)               # one place for the chip rules
        self.assertNotIn(".why", LAYOUT_CSS + LAYOUT_DASH_CSS)
        self.assertIn("#session-list .srow.has-why>summary .t{flex-wrap:wrap", LAYOUT_TOKEN_CSS)
        self.assertNotRegex(LAYOUT_TOKEN_CSS + LAYOUT_DASH_CSS, r"#session-list \.srow>summary \.t\{[^}]*flex-wrap")  # every other row keeps one ellipsised line
        self.assertIn("el.classList.toggle('has-why',!!why)", JS_SESSIONS)
        # a row without a chip keeps its ellipsis: the title and its cell clip, so a long unbroken title cannot push the tokens
        self.assertIn(".srow>summary .tt{overflow:hidden;text-overflow:ellipsis;min-width:0}", LAYOUT_CSS)
        self.assertIn(".srow>summary .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}", LAYOUT_CSS)
        # the two-line phone list is in the sheet the static report loads too (its title column was 0 px wide)
        self.assertIn("#session-list{--scols:44px auto minmax(0,1fr) 72px 24px}", LAYOUT_CSS)
        self.assertNotIn("--scols:44px auto", LAYOUT_DASH_CSS)

    def test_the_filter_placeholder_names_the_folder(self):
        conn = connect(Path(tempfile.mkdtemp()) / "t.db")
        page = dashboard.page_sessions(conn, dashboard.Filters({"range": ["all"]}), {})
        self.assertIn("Filter by title, skill, folder or session id", page)
        self.assertIn("class=why hidden", JS_SESSIONS)

    def test_pages_ask_for_new_data_every_2_seconds(self):
        # the "New data · reload" button and the live numbers wait at most this long after an ingest
        self.assertIn("setInterval(poll,2000)", dashboard.DASH_JS)

    def test_the_from_label_links_only_where_the_dashboard_serves_sessions(self):
        js = JS_SESSIONS
        # an orphan child links to its parent's full id, all time; the id is URL-encoded and the name escaped
        self.assertIn("DASH&&s.parent?`<a href=\"/sessions?range=all&amp;q=${encodeURIComponent(s.parent)}\"", js)
        self.assertIn("${esc(by)}</a>`:esc(by)", js)
        # the static report's body has no data-page, so it keeps plain text
        self.assertIn("const DASH=!!document.body.dataset.page", js)

    def test_a_parent_with_many_children_can_collapse_again(self):
        js = JS_SESSIONS
        self.assertIn("'Show fewer'", js)
        self.assertIn("setAttribute('aria-expanded'", js)
        self.assertIn("openKids.delete(id)", js)


class SkinSwitchReportTest(unittest.TestCase):
    def test_a_report_carries_both_skins_and_the_switch_button(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "t.db"
            connect(db).close()
            out = Path(d) / "r.html"
            from tokscope.web.report import write_report
            write_report(db, out, tasks_dir=Path(d))
            page = out.read_text()
        self.assertIn('<style id="skin-ink">', page)
        self.assertIn('<style id="skin-classic" media="not all">', page)
        self.assertIn('id="skin"', page)

    def test_one_layout_sheet_comes_before_both_skins(self):
        from tokscope.web.theme.classic import CLASSIC_CSS
        from tokscope.web.theme.layout import LAYOUT_CSS
        from tokscope.web.report import write_report
        from tokscope.web.report.styles import CSS
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
        from tokscope.web.theme.classic import CLASSIC_CSS, CLASSIC_DASH_CSS
        from tokscope.web.theme.layout import LAYOUT_CSS, LAYOUT_DASH_CSS
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

    def test_the_session_start_line_is_marked_as_an_estimate_and_follows_the_range(self):
        self.add(2, tokens=3000)
        self.add(40, tokens=1000)                                   # the session's first request, not the 2-day-old one
        page = overview_page._session_start(self.conn, dashboard.Filters({"range": ["90"]}))
        self.assertIn("Every new session starts at ~1.0K tokens (~$0.01)", page)
        self.assertIn("Estimate.", page)
        self.assertIn("median of 1 session", page)
        self.assertIn("No sessions in this range.", overview_page._session_start(self.conn, dashboard.Filters({"range": ["7"]})))

    def test_the_session_start_line_says_so_when_the_range_has_no_session(self):
        page = overview_page._session_start(self.conn, dashboard.Filters({"range": ["7"]}))
        self.assertIn("No sessions in this range.", page)
        self.assertNotIn("Every new session", page)

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
        window = overview_page._window(self.conn, dashboard.Filters({"range": ["7"]}))
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
        self.assertEqual(shell._filter_pill(self.conn, f, "overview"), "Last 7 days · all projects · opus-5-5 · plan")
        self.assertEqual(shell._filter_pill(self.conn, f, "library"), "all projects")

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
        from tokscope.web.theme.layout import LAYOUT_DASH_CSS
        block = LAYOUT_DASH_CSS.split("/* phone */", 1)[1].split("/* end phone */", 1)[0]
        self.assertIn("@media (max-width:639px)", block)
        self.assertIn("min-height:44px", block)
        self.assertIn("prefers-reduced-motion:reduce", block)                      # the sheet fades, it does not travel
        self.assertNotIn("menu-btn", report_scripts.JS)
        self.assertIn(".spenders td:first-child a,.spenders td:first-child span{display:inline-flex;align-items:flex-end;", block)  # name sits on its numbers, no loose gap

    def test_phone_breakpoint_is_639_in_css_and_script_and_the_sheet_leaves_dialog_and_select_keys_alone(self):
        from tokscope.web.theme.layout import LAYOUT_DASH_CSS
        from tokscope.web.theme.classic import CLASSIC_DASH_CSS
        block = LAYOUT_DASH_CSS.split("/* phone */", 1)[1].split("/* end phone */", 1)[0]
        self.assertNotIn("max-width:640px", block)
        self.assertNotIn("max-width:640px", CLASSIC_DASH_CSS.split("/* end overview */", 1)[1])
        self.assertIn("matchMedia('(max-width:639px)')", dashboard.DASH_JS)
        keys = dashboard.DASH_JS.split("document.addEventListener('keydown',e=>{if(!sheet.classList.contains('open'))return;", 1)[1][:400]
        self.assertIn("dialog[open]", keys.split("if(e.key==='Escape')", 1)[0])    # the shortcuts dialog keeps Escape and Tab
        self.assertIn("selOpen", keys)                                             # an open select keeps its Escape

    def test_classic_phone_controls_get_an_outline_that_reads_3_to_1(self):
        from tokscope.web.theme.classic import CLASSIC_DASH_CSS
        rule = CLASSIC_DASH_CSS.split("the new controls have no other cue", 1)[1]
        self.assertIn("body .menu-btn", rule)
        self.assertIn("border-color:var(--muted)", rule.split("}", 1)[0])
        self.assertIn("4.69:1", CLASSIC_DASH_CSS)                                  # the measured ratio, not 4.0

    def test_a_window_before_shorter_than_the_range_is_compared_per_day(self):
        self.add_hours(40 * 24)                                            # the same 100 an hour for 40 days
        body = self.page()                                                 # 30 days; only 9.96 days of data before them
        self.assertIn("against the 9 days before it", body)
        self.assertIn('<span class="trend flat">+0%</span>', body)         # not -67%, which 10 days over 30 would read as
        window = overview_page._window(self.conn, dashboard.Filters({}))
        self.assertEqual(window["now"], 30)
        self.assertAlmostEqual(window["before"], 9.96, places=1)

    def test_no_comparison_for_all_time_or_with_nothing_before_the_range(self):
        for d in range(20):
            self.add(d)
        self.assertIsNone(overview_page._window(self.conn, dashboard.Filters({"range": ["all"]})))
        self.assertIsNone(overview_page._window(self.conn, dashboard.Filters({})))        # 20 days of history, 30-day range
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
        self.assertEqual(overview_page._at_hour(typ["med"], 9.5), typ["med"][9] + (typ["med"][10] - typ["med"][9]) / 2)

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

    def test_only_the_version_that_replaced_another_gets_a_mark(self):
        for d in (7, 4, 1):                                                # both versions are first seen inside the chart
            self.add(d)
        self.conn.executescript(skills.SCHEMA)
        self.conn.executemany("INSERT INTO skill_versions (skill, version, first_seen, source, label) VALUES (?,?,?,?,?)",
                              [("xia2", "aaaaaa111111", self.ts(5), "disk", None), ("xia2", "bbbbbb222222", self.ts(2), "disk", None)])
        body = self.page()
        self.assertIn("xia2 bbbbbb", body)                                 # the second version replaced the first
        self.assertNotIn("xia2 aaaaaa", body)                              # the first sight of a skill is not a change
        self.assertIn('<code class="ver">bbbbbb</code>', body)             # the "New skill versions" list agrees with the lines
        self.assertNotIn('<code class="ver">aaaaaa</code>', body)

    def test_models_are_listed_by_requests_and_link_to_the_model_filter(self):
        def req(key, model):
            self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, "
                              "cache_write_5m, cache_write_1h, cost_usd) VALUES ('s1',?,?,?,1,10,0,0,0,0,0.1)", (key, self.ts(1), model))
        for i in range(1200):
            req(f"a{i}", "claude-haiku-5-5")
        req("b0", "claude-opus-5-5")
        body = overview_page._models(self.conn, dashboard.Filters({}))
        self.assertLess(body.index("claude-haiku-5-5"), body.index("claude-opus-5-5"))   # 1,200 requests before 1
        self.assertIn("100%", body)
        self.assertIn("1,200", body)   # a request count is exact; the bar column's token format would write 1.2K
        self.assertIn('href="/overview?model=claude-opus-5-5"', body)
        self.assertIn("Nothing in this range.", overview_page._models(self.conn, dashboard.Filters({"range": ["7"], "project": ["none"]})))
        self.assertIn('<div data-region="models">', self.page())

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
        svg = overview_page._daily_stacked(rows, [], [])
        wide = svg.split('<svg class="narrow"')[0]                          # the phone shows a second, narrow copy
        self.assertEqual(wide.count('<g class="d"'), 7)                     # days off are empty slots
        # wide chart: the baseline is y 218 (240 - pad_b 22) and the plot is 184 high (240 - 34 - 22)
        last = re.search(r'class="ma"[^>]*points="([^"]+)"', wide).group(1).split()[-1]
        self.assertEqual(last.split(",")[1], f"{218 - 184 * (2000 / 7) / 1000:.1f}")  # 2000 over 7 calendar days, not 1000

    def test_the_y_axis_labels_the_gridlines_where_they_are(self):
        marks = {k: [0] * 25 for k in ("p25", "med", "p75")}
        marks["p75"] = [100] * 25
        svg = overview_page._today_chart({**marks, "n": 9}, [(0, 0)], 1.0, 100)
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
        hours = overview_page._hours(self.conn, dashboard.Filters({}))
        local = day.astimezone()
        self.assertEqual((local.hour, local.minute), (6, 0))                # 00:30 UTC is 06:00 in Kolkata
        self.assertEqual(hours[local.date()][6], 500)
        self.assertEqual(sum(hours[local.date()]), 500)

    def test_sidebar_counts_are_cached_and_follow_the_folded_projects(self):
        self.conn.commit()
        with mock.patch.object(features_library, "discover", return_value=[1, 2, 3]) as lib, \
                mock.patch.object(features_projects, "discover", return_value=[{"root": "/a"}, {"root": "/b"}, {"root": None}]):
            shell._NAV_CACHE.clear()
            first = shell._nav_counts(self.conn)
            shell._nav_counts(self.conn)
        self.assertEqual((first["projects"], first["library"]), (2, 3))     # the Projects page's folded groups, benchmark rows left out
        self.assertEqual(lib.call_count, 1)                                 # the second render reads the cache
        self.assertEqual(set(shell._nav_counts(self.conn, "numbers")), {"sessions"})


class ServeProjectsDirTest(unittest.TestCase):
    def serve_args(self, *argv):
        from tokscope import cli
        with mock.patch.object(sys, "argv", ["tokscope", "serve", "--no-open", *argv]), mock.patch.object(dashboard, "serve") as serve:
            cli.main()
        return serve.call_args

    def test_serve_reads_the_transcripts_folder_it_is_given_and_the_default_ones_otherwise(self):
        sample = tempfile.mkdtemp()
        self.assertEqual(self.serve_args("--projects-dir", sample, "--privacy", "redacted").kwargs["projects_dir"], sample)
        self.assertIsNone(self.serve_args().kwargs["projects_dir"])  # None: ingest picks ~/.claude/projects and the others

    def test_a_folder_that_does_not_exist_or_an_empty_value_stops_serve_before_it_starts(self):
        for bad in ("/no/such/folder", ""):
            with self.assertRaises(SystemExit) as raised:
                self.serve_args("--projects-dir", bad)
            self.assertIn("is not a folder", str(raised.exception))

    def test_the_dashboard_ingests_from_the_folder_it_is_given(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "p").mkdir()
        with mock.patch("tokscope.web.dashboard.server.ingest") as ing:
            dashboard.Live(tmp / "t.db", ASSETS / "phases.json", 60, projects_dir=tmp / "p").tick()
        self.assertEqual(ing.call_args.args[2], tmp / "p")
