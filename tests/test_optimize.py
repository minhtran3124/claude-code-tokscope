import json
import os
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.core import skills
from tokscope.experiments import optimize
from tokscope.features import changes, library
from tokscope.web import dashboard
from http.server import BaseHTTPRequestHandler
from tokscope.web.dashboard.pages import library as library_page
from tokscope.core.ingest import connect

# stands in for claude -p: rewrites the target's SKILL.md in its cwd, notes its arguments, answers like --output-format json
FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, signal, sys, time
from pathlib import Path
Path(os.environ["FAKE_ARGS"]).write_text(json.dumps(sys.argv[1:]))
say = lambda ev: print(json.dumps(ev), flush=True)
say({"type": "system", "subtype": "init", "model": "claude-sonnet-5-5"})
if os.environ.get("FAKE_SLOW"):  # waits to be cancelled; SIGINT ends the turn with a result, as claude -p does
    def stop(*_):
        say({"type": "result", "is_error": True, "result": "interrupted", "total_cost_usd": 0.05}); sys.exit(130)
    signal.signal(signal.SIGINT, stop)
    time.sleep(30)
if os.environ.get("FAKE_FAIL"):
    say({"type": "result", "is_error": True, "result": "budget exceeded", "total_cost_usd": 2.0}); sys.exit(1)
target = next(p for p in Path(".claude/skills").iterdir() if p.name not in ("asd-ste100", "unslop", "optimize-skill"))
say({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
    {"type": "text", "text": "I will shorten the skill.\\nMore detail."},
    {"type": "tool_use", "name": "Read", "input": {"file_path": str((target / "SKILL.md").resolve())}}]}})
say({"type": "assistant", "parent_tool_use_id": "toolu_1", "message": {"content": [
    {"type": "tool_use", "name": "Skill", "input": {"skill": "unslop"}}]}})
say({"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "denied: Bash(rm x)"}]}})
(target / "SKILL.md").write_text("---\\nname: mine-a\\ndescription: Does a thing.\\n---\\nShort text.\\n")
(target / "references").mkdir(exist_ok=True)
(target / "references" / "moved.md").write_text("Moved here.\\n")
say({"type": "result", "is_error": False, "result": "Cut 40 words.", "total_cost_usd": 0.12, "session_id": "s-opt", "num_turns": 3})
"""


def skill(folder, name, body="# Title\n\nLong text that says a thing in many words.\n"):
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Does a thing.\n---\n{body}")
    return folder


class OptimizeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        home = self.tmp / "h"
        fake = self.tmp / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.args = self.tmp / "args.json"
        env = mock.patch.dict(os.environ, {"HOME": str(home), "TOKSCOPE_HOME": str(self.tmp / "data"),
                                           "TOKSCOPE_CLAUDE": str(fake), "FAKE_ARGS": str(self.args)})
        env.start()
        self.addCleanup(env.stop)
        self.os_env = os.environ
        personal = home / ".claude" / "skills"
        self.src = skill(personal / "mine-a", "mine-a")
        (self.src / ".git-keep").write_text("hidden files stay")
        skill(personal / "unslop", "unslop")
        agents = skill(home / ".agents" / "skills" / "asd-ste100", "asd-ste100")
        (personal / "asd-ste100").symlink_to(agents)               # installed, and still usable as a guide
        self.conn = connect(self.tmp / "t.db")
        self.found = library.discover(self.conn)
        self.k = next(k for k in self.found if k["dir"] == "mine-a")

    def test_a_run_works_on_a_copy_within_the_budget_and_leaves_the_skill_alone(self):
        before = (self.src / "SKILL.md").read_text()
        job = optimize.start(self.k, self.found, ["unslop", "asd-ste100"], "sonnet", 1.5, wait=True)
        data = optimize.status(job)
        self.assertEqual((data["state"], data["cost"], data["report"]), ("done", 0.12, "Cut 40 words."))
        self.assertEqual((self.src / "SKILL.md").read_text(), before)
        args = json.loads(self.args.read_text())
        self.assertEqual(args[args.index("--max-budget-usd") + 1], "1.5")
        self.assertEqual(args[args.index("--model") + 1], "sonnet")
        root = optimize.jobs_dir() / job
        self.assertIn(f"Edit(/{root}/**)", args)                  # writes stay inside the job folder
        self.assertNotIn("Bash", args)                             # no open shell, only the two named commands
        self.assertIn("bench", str(root))                          # its sessions count as experiments
        kinds = {rel: kind for rel, kind, _ in optimize.changes(job)}
        self.assertEqual(kinds, {"SKILL.md": "changed", "references/moved.md": "added"})

    def test_each_step_of_the_stream_is_kept_for_the_page(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        args = json.loads(self.args.read_text())
        self.assertEqual(args[args.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", args)
        shown, total, _ = optimize.steps(job)
        texts = [(st["kind"], st["text"], st["sub"]) for st in shown]
        self.assertEqual(texts[0], ("start", "started · claude-sonnet-5-5", False))
        self.assertIn(("say", "I will shorten the skill.", False), texts)        # the first line only
        self.assertIn(("tool", "Read .claude/skills/mine-a/SKILL.md", False), texts)  # relative to the job folder
        self.assertIn(("tool", "Skill unslop", True), texts)                    # inside a subagent
        self.assertIn(("error", "tool error: denied: Bash(rm x)", False), texts)
        self.assertEqual(texts[-1][:2], ("end", "done"))
        self.assertEqual(optimize.status(job)["turns"], 3)
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]], "job": [job]}, "full")
        self.assertIn('<div class="outcome ok"><b>✓ Done in', page)
        self.assertIn("2 files changed</b>", page)

    def test_a_running_job_can_be_cancelled_and_keeps_what_it_spent(self):
        os.environ["FAKE_SLOW"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_SLOW", None)
        job = optimize.start(self.k, self.found, ["unslop"])
        thread = optimize._threads[job]  # taken now: the run removes itself from _threads when it ends
        for _ in range(100):
            if optimize.steps(job)[1]:
                break
            time.sleep(0.05)
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]], "job": [job]}, "full")
        self.assertIn('id="run-elapsed"', page)
        self.assertIn('data-job-act="cancel"', page)
        skill_page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]]}, "full")
        self.assertIn("An optimize run is going", skill_page)
        optimize.cancel(job)
        thread.join(10)
        data = optimize.status(job)
        self.assertEqual((data["state"], data["cost"]), ("cancelled", 0.05))
        with self.assertRaises(ValueError):
            optimize.cancel(job)                                   # not running any more

    def test_apply_writes_the_copy_and_records_both_versions(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        old_version = skills.fingerprint(self.src)
        old, new = optimize.apply(self.conn, job)
        self.assertEqual(old, old_version)
        self.assertEqual(new, skills.fingerprint(self.src))
        self.assertNotEqual(old, new)
        self.assertIn("Short text.", (self.src / "SKILL.md").read_text())
        self.assertTrue((self.src / "references" / "moved.md").is_file())
        self.assertTrue((self.src / ".git-keep").is_file())        # a hidden file is not the run's to remove
        kept = {v for (v,) in self.conn.execute("SELECT version FROM skill_versions WHERE skill = 'mine-a'")}
        self.assertEqual(kept, {old, new})
        self.assertTrue(skills.snapshot_dir("mine-a", old).is_dir())  # the old files stay for a diff or a benchmark
        with self.assertRaises(ValueError):
            optimize.apply(self.conn, job)                         # only once

    def test_apply_refuses_when_the_skill_changed_after_the_job_started(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        (self.src / "SKILL.md").write_text("---\nname: mine-a\n---\nEdited by hand meanwhile.\n")
        with self.assertRaisesRegex(ValueError, "changed after this job started"):
            optimize.apply(self.conn, job)
        self.assertIn("Edited by hand", (self.src / "SKILL.md").read_text())

    def test_a_failed_run_keeps_its_cost_and_error_and_can_be_discarded(self):
        os.environ["FAKE_FAIL"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_FAIL", None)
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        data = optimize.status(job)
        self.assertEqual((data["state"], data["cost"], data["error"]), ("failed", 2.0, "budget exceeded"))
        with self.assertRaises(ValueError):
            optimize.apply(self.conn, job)
        optimize.discard(job)
        self.assertFalse((optimize.jobs_dir() / job).exists())

    def test_installed_skills_bad_guides_and_bad_budgets_are_refused(self):
        installed = next(k for k in self.found if k["dir"] == "asd-ste100")
        for k, guides, budget in ((installed, ["unslop"], 2), (self.k, [], 2), (self.k, ["optimize-skill"], 2),
                                  (self.k, ["unslop"], 0), (self.k, ["unslop"], 999)):
            with self.assertRaises(ValueError):
                optimize.start(k, self.found, guides, "", budget)
        self.assertFalse(optimize.jobs_dir().exists())

    def test_the_job_page_shows_the_diff_and_the_apply_button(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]], "job": [job]}, "full")
        self.assertIn('data-job-act="apply"', page)
        self.assertIn("<span class='add'>+Short text.</span>", page)
        self.assertIn("references/moved.md", page)
        self.assertIn("Cut 40 words.", page)
        skill_page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]]}, "full")
        self.assertIn(f"job={job}", skill_page)                    # listed under earlier runs
        self.assertIn('value="asd-ste100" checked', skill_page)    # an installed guide is still offered
        self.assertIn('value="optimize-skill" disabled', skill_page)


BENCH_CLAUDE = """#!/usr/bin/env python3
import json, sys, uuid
from pathlib import Path
if "--version" in sys.argv:
    print("2.1.305 (Claude Code)"); sys.exit()
body = next(Path(".claude/skills").glob("*/SKILL.md")).read_text()
print(json.dumps({"is_error": False, "result": "CLAUDE_MODEL in ai_config", "session_id": "b-" + uuid.uuid4().hex,
                  "total_cost_usd": round(len(body) / 10000, 4)}))
"""


class ApplyChangeRowTest(OptimizeTest):
    def rows(self):
        return changes.list_changes(self.conn)

    def test_apply_adds_one_row_for_the_skill_at_the_applied_time(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        optimize.apply(self.conn, job)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][1], rows[0][3], rows[0][4]), (optimize.status(job)["applied"], None, "mine-a"))

    def test_a_refused_apply_adds_no_row(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        (self.src / "SKILL.md").write_text("---\nname: mine-a\n---\nEdited by hand meanwhile.\n")
        with self.assertRaises(ValueError):
            optimize.apply(self.conn, job)                         # the skill changed
        os.environ["FAKE_FAIL"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_FAIL", None)
        failed = optimize.start(self.k, self.found, ["unslop"], wait=True)
        with self.assertRaises(ValueError):
            optimize.apply(self.conn, failed)                      # not done
        self.assertEqual(self.rows(), [])

    def test_a_second_apply_adds_no_second_row(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        optimize.apply(self.conn, job)
        with self.assertRaises(ValueError):
            optimize.apply(self.conn, job)
        self.assertEqual(len(self.rows()), 1)

    def test_the_row_is_measured_with_requests_on_both_sides(self):
        applied = datetime.now(timezone.utc) - timedelta(days=2)
        self.conn.execute("INSERT INTO sessions (session_id, project) VALUES ('s1', '-home-u-app')")
        for i, delta in enumerate((-30, -20, 20, 30)):
            ts = (applied + timedelta(hours=delta)).isoformat()
            self.conn.execute("INSERT INTO requests (session_id, request_key, ts, skill, prompt_idx, input, output, cache_read, "
                              "cache_write_5m, cache_write_1h) VALUES ('s1', ?, ?, 'mine-a', ?, 10, 5, 0, 0, 0)", (f"k{i}", ts, i))
        self.conn.commit()
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        with mock.patch.object(optimize, "_now", return_value=applied.isoformat(timespec="seconds")):
            optimize.apply(self.conn, job)
        r = changes.impact(self.conn, self.rows()[0])
        self.assertGreater(r["before"]["n"], 0)
        self.assertGreater(r["after"]["n"], 0)


class ApplyChangeFailureTest(OptimizeTest):
    def test_a_failed_changes_row_keeps_the_apply_and_records_change_error(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        with mock.patch.object(changes, "add_change", side_effect=sqlite3.OperationalError("database is locked")):
            old, new = optimize.apply(self.conn, job)
        data = optimize.status(job)
        self.assertEqual((data["old_version"], data["new_version"]), (old, new))
        self.assertEqual(data["state"], "applied")
        self.assertIn("database is locked", data["change_error"])
        self.assertIn("Short text.", (self.src / "SKILL.md").read_text())
        self.assertEqual(changes.list_changes(self.conn), [])

    def test_a_working_changes_row_leaves_no_change_error(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        optimize.apply(self.conn, job)
        self.assertNotIn("change_error", optimize.status(job))
        self.assertEqual(len(changes.list_changes(self.conn)), 1)

    def test_a_refused_apply_raises_and_writes_no_change_error(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        (self.src / "SKILL.md").write_text("---\nname: mine-a\n---\nEdited by hand meanwhile.\n")
        with self.assertRaises(ValueError):
            optimize.apply(self.conn, job)
        self.assertNotIn("change_error", optimize.status(job))
        self.assertEqual(changes.list_changes(self.conn), [])


class CompareAndBenchTest(OptimizeTest):
    def test_the_result_compares_side_by_side_and_asks_for_a_decision(self):
        job = optimize.start(self.k, self.found, ["unslop"], wait=True)
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]], "job": [job]}, "full")
        for tab in ("sbs", "diff", "after", "before"):
            self.assertIn(f'data-cmp="{tab}"', page)
        self.assertIn('<td class="add"><mark>Short text.</mark></td>', page)      # a changed line, its words marked
        self.assertIn('class="decide"', page)
        self.assertIn(">Approve and apply</button>", page)
        self.assertIn(">Reject</button>", page)
        self.assertIn("cannot be benchmarked", page)                                # a personal skill wins over a pin
        optimize.apply(self.conn, job)
        page = dashboard.page_library(self.conn, dashboard.Filters({}), {"skill": [self.k["id"]], "job": [job]}, "full")
        self.assertIn("✓ Approved and applied", page)
        self.assertIn('<td class="add"><mark>Short text.</mark></td>', page)      # still compared, from the kept versions
        self.assertNotIn('class="decide"', page)

    def test_a_project_skill_draft_is_benchmarked_against_the_skill(self):
        import subprocess
        home = Path(os.environ["HOME"])
        repo = home / "work" / "repo"
        skill(repo / ".claude" / "skills" / "proj-skill", "proj-skill", body="# Proj\n\nA long body. " * 20)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('p1', '-repo', ?, 't', 1)", (str(repo),))
        self.conn.commit()
        found = library.discover(self.conn)
        k = next(x for x in found if x["dir"] == "proj-skill")
        self.assertFalse((home / ".claude" / "skills" / "proj-skill").exists())   # a project skill, so it can be pinned
        fake = home / ".local" / "bin" / "claude"                              # where bench looks for claude
        fake.parent.mkdir(parents=True)
        fake.write_text(BENCH_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        os.environ["TOKSCOPE_CLAUDE"] = str(self.tmp / "claude")                     # the optimize run keeps its fake
        job = optimize.start(k, found, ["unslop"], wait=True)
        self.assertEqual(optimize.status(job)["state"], "done")
        with self.assertRaisesRegex(ValueError, "pick another name"):
            optimize.new_task("proj-skill", k["folder"], {"name": "x", "prompt": "/proj-skill hi"}) and \
                optimize.new_task("proj-skill", k["folder"], {"name": "x", "prompt": "/proj-skill hi"})
        name = optimize.new_task("proj-skill", k["folder"], {"name": "proj-quick", "prompt": "/proj-skill which model?",
                                                             "grader": "CLAUDE_MODEL, ai_config", "paths": "."})
        tasks = optimize.bench_tasks("proj-skill")
        self.assertEqual(tasks[0][0], name)
        self.assertTrue(tasks[0][3])                                                 # it uses the skill: listed first
        db = self.tmp / "t.db"
        started = optimize.bench_start(job, db, name, 1)
        self.assertEqual(started["cap"], 3.0)                                       # 1 run x 2 versions x $1.5
        optimize._bench_threads[job].join(60)
        self.assertEqual(optimize.bench_status(job)["state"], "done", optimize.bench_status(job))
        current, draft = optimize.bench_results(job, db)
        self.assertEqual((current["label"], current["runs"], current["passed"]), ("current", 1, 1))
        self.assertEqual((draft["label"], draft["runs"], draft["passed"]), ("draft", 1, 1))
        self.assertLess(draft["cost"], current["cost"])                              # the fake costs by SKILL.md size
        page = library_page._bench_section(job, optimize.status(job), self.conn)
        self.assertIn("Draft against current:</b> pass 1/1 vs 1/1, cost", page)
        with self.assertRaisesRegex(ValueError, "runs per version"):
            optimize.bench_start(job, db, name, 4)


class WriteGuardTest(OptimizeTest):
    def setUp(self):
        super().setUp()
        live = dashboard.Live(self.tmp / "t.db", paths.ASSETS / "phases.json", 60, projects_dir=self.tmp)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = dashboard.handler(self.tmp / "t.db", live, self.port, "full", token="tok")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, body, headers):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_write_needs_this_origin_the_page_token_and_json(self):
        body = {"skill": self.k["id"], "guides": ["unslop"], "budget": 1}
        good = {"Origin": f"http://127.0.0.1:{self.port}", "X-Tokscope-Token": "tok", "Content-Type": "application/json"}
        self.assertEqual(self.post("/api/optimize", body, {**good, "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/api/optimize", body, {k: v for k, v in good.items() if k != "Origin"})[0], 403)
        self.assertEqual(self.post("/api/optimize", body, {**good, "X-Tokscope-Token": "guess"})[0], 403)
        self.assertEqual(self.post("/api/optimize", body, {**good, "Content-Type": "text/plain"})[0], 415)
        self.assertFalse(optimize.jobs_dir().exists())              # nothing ran
        code, out = self.post("/api/optimize", body, good)
        self.assertEqual(code, 200)
        self.assertEqual(self.post(f"/api/optimize/{out['job']}/../../x/apply", {}, good)[0], 404)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/library") as r:
            self.assertIn('<meta name="tokscope-token" content="tok">', r.read().decode())


if __name__ == "__main__":
    unittest.main()
