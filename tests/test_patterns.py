"""tokscope patterns: text helpers, facets, grouping, privacy levels and the command."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import mock

from tokscope import cli
from tokscope.core import tz
from tokscope.core.ingest import connect
from tokscope.features import patterns


class TextTest(unittest.TestCase):
    def test_mask_tokens(self):
        for raw in ("sk-ant-api03-abcDEF123", "ghp_abcdefghijklmnop", "token=abc123", "TOKEN=abc123", "api_key=zzz",
                    "Bearer abc.def", "password: hunter2", "x" * 40):
            self.assertIn("[masked]", patterns.mask(f"use {raw} now"), raw)
            self.assertNotIn(raw, patterns.mask(f"use {raw} now"))

    def test_mask_aws_and_phrased_secrets(self):
        for raw in ("AKIAIOSFODNN7EXAMPLE", "ASIAIOSFODNN7EXAMPLE", "password is hunter2", "api-key: abc123",
                    "API-KEY=abc123", "passwd: x1"):
            out = patterns.mask(f"use {raw} now")
            self.assertIn("[masked]", out, raw)
            self.assertNotIn(raw.split()[-1], out, raw)

    def test_mask_phrased_password_variants(self):
        for raw, secret in (("password is: hunter2", "hunter2"), ("password was hunter2", "hunter2"),
                            ("password for bob is hunter2", "hunter2"), ("passphrase: hunter2", "hunter2")):
            out = patterns.mask(f"use {raw} now")
            self.assertIn("[masked]", out, raw)
            self.assertNotIn(secret, out, raw)

    def test_mask_snake_case_names(self):
        for raw in ("client_secret=abc1", "access_token: abc1", "DB_PASSWORD=abc1", "my-api-key=abc1"):
            out = patterns.mask(f"set {raw} now")
            self.assertEqual(out, "set [masked] now", raw)

    def test_mask_fragments_and_boundary(self):
        self.assertEqual(patterns.mask("key sk-"), "key [masked]")
        self.assertEqual(patterns.mask("see ghp_"), "see [masked]")
        for ok in ("task-key", "risk-free", "disk-usage"):
            self.assertEqual(patterns.mask(ok), ok)

    def test_example_masks_before_the_cut(self):
        text = "sk-ant-" + "a" * 100 + " then ghp_" + "b" * 10 + " end"
        out = patterns._example(text)
        self.assertEqual(out, "[masked] then [masked] end")
        # a token that crosses the 80 character cut is gone, not half shown
        out = patterns._example("w " * 38 + "ghp_" + "c" * 30 + " tail")
        self.assertNotIn("ghp_", out)
        self.assertLessEqual(len(patterns._example("word " * 50)), 80)
        self.assertTrue(patterns._example("word " * 50).endswith("…"))
        self.assertIsNone(patterns._example(""))
        self.assertIsNone(patterns._example(None))

    def test_task_key(self):
        self.assertEqual(patterns._task_key("Fix the failing test in module A now please"), "fix the failing test in")
        self.assertEqual(patterns._task_key("fix 42 src/a.py ~/x .git the bug 2024 again"), "fix the bug again")
        self.assertIsNone(patterns._task_key("12 /a ~b .c"))
        self.assertIsNone(patterns._task_key(""))

    def test_token_in_task_key(self):
        key = patterns._task_key("use ghp_abcdefghijkl to push the thing")
        self.assertNotIn("ghp_", key)
        self.assertIn("[masked]", key)


class FacetsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.facets = self.root / "usage-data" / "facets"
        self.facets.mkdir(parents=True)

    def write(self, name, text):
        (self.facets / name).write_text(text)

    def outcome(self, sid="s1", dirs=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            found = patterns._outcome(sid, dirs or [self.facets])
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        return found

    def test_value(self):
        self.write("s1.json", json.dumps({"session_id": "s1", "outcome": "mostly_achieved", "brief_summary": "SECRET text"}))
        self.assertEqual(self.outcome(), "mostly_achieved")

    def test_missing_folder_and_file(self):
        self.assertIsNone(self.outcome("nope"))
        self.assertIsNone(self.outcome(dirs=[self.root / "absent"]))

    def test_bad_shapes(self):
        cases = {"bad.json": "{not json", "list.json": "[1]", "none.json": "{}", "num.json": '{"outcome": 5}',
                 "null.json": '{"outcome": null}', "free.json": '{"outcome": "The user was happy."}',
                 "nl.json": '{"outcome": "done\\n"}', "long.json": json.dumps({"outcome": "a" * 41}),
                 "bin.json": ""}
        for name, text in cases.items():
            self.write(name, text)
            self.assertIsNone(self.outcome(name[:-5]), name)
        (self.facets / "bytes.json").write_bytes(b"\xff\xfe")
        self.assertIsNone(self.outcome("bytes"))

    def test_session_id_cannot_leave_the_folder(self):
        (self.root / "usage-data" / "evil.json").write_text('{"outcome": "x"}')
        self.assertIsNone(self.outcome("../evil"))

    def test_dirs_from_env(self):
        other = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": f"{self.root}, {other}"}):
            self.assertEqual(patterns._facet_dirs(), [self.facets, other / "usage-data" / "facets"])
        with mock.patch.dict(os.environ, {"HOME": str(other)}), mock.patch.dict(os.environ):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertEqual(patterns._facet_dirs(), [other / ".claude" / "usage-data" / "facets"])

    def test_first_hit_wins(self):
        other = Path(tempfile.mkdtemp())
        (other / "s1.json").write_text('{"outcome": "second"}')
        self.write("s1.json", '{"outcome": "first"}')
        self.assertEqual(self.outcome(dirs=[self.facets, other]), "first")
        self.assertEqual(self.outcome("s1", [self.root / "absent", other]), "second")


LONG = "please refactor the billing module carefully"  # 25 characters or more
CANARY = "CANARY-PROMPT acme invoices"


def stamp(days=1, minutes=0):
    t = datetime.now(timezone.utc) - timedelta(days=days) + timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        for name, value in (("TOKSCOPE_HOME", self.dir / "home"), ("CLAUDE_CONFIG_DIR", self.dir / "claude")):
            patcher = mock.patch.dict(os.environ, {name: str(value)})
            patcher.start()
            self.addCleanup(patcher.stop)
        self.facets = self.dir / "claude" / "usage-data" / "facets"
        self.facets.mkdir(parents=True)
        self.db = self.dir / "t.db"
        self.conn = connect(self.db)
        self.n = 0

    def session(self, sid, project="-home-u-app"):
        self.conn.execute("INSERT OR IGNORE INTO sessions (session_id, project, cwd, title, prompts) VALUES (?, ?, '/x', 't', 1)",
                          (sid, project))

    def prompt(self, sid, idx, text, days=1, project="-home-u-app", skills=(), reqs=None, sub_skills=()):
        """A prompt with its requests (default: one priced main-thread request) and skill loads."""
        self.session(sid, project)
        if text is not None:
            self.conn.execute("INSERT INTO prompts VALUES (?, ?, ?, ?)", (sid, idx, stamp(days), text))
        for r in reqs if reqs is not None else [dict()]:
            self.request(sid, idx, days=days, **r)
        for i, skill in enumerate(skills):
            self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, prompt_idx, failed) VALUES (?, ?, ?, ?, 0)",
                              (sid, stamp(days, i), skill, idx))
        for skill in sub_skills:
            self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, prompt_idx, agent_id, failed) "
                              "VALUES (?, ?, ?, ?, 'ag1', 0)", (sid, stamp(days, 5), skill, idx))

    def request(self, sid, idx, model="claude-opus-5-5", cost=1.0, cr=0, inp=10, w5=0, w1=0, agent=None, days=1, minutes=0):
        self.n += 1
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, agent_id, prompt_idx, input, output, "
                          "cache_read, cache_write_5m, cache_write_1h, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                          (sid, f"k{self.n}", stamp(days, minutes + self.n / 100), model, agent, idx, inp, cr, w5, w1, cost))

    def go(self, level="full", since=None):
        self.conn.commit()
        self.conn.close()
        bound = tz.utc_bound(since or patterns.default_since())
        result = patterns.run(self.db, bound, level)
        self.conn = connect(self.db)
        return result

    def keys(self, level="full", **kw):
        return {(g["kind"], g["key"]) for g in self.go(level, **kw)["groups"]}


class GroupingTest(Base):
    def test_exclusions(self):
        self.prompt("b", 1, LONG, skills=["sk1"], project="-home-u-tokscope-bench-1")  # bench session
        self.prompt("m", 1, "<command-name>x</command-name> and more text", skills=["sk2"])  # machine prompt
        self.prompt("n", None, None, reqs=[dict()])  # NULL prompt_idx
        self.conn.execute("UPDATE requests SET prompt_idx = NULL WHERE session_id = 'n'")
        self.prompt("o", 7, None)  # prompt_idx with no prompts row
        self.prompt("s", 1, "ok thanks")  # short, no skill
        for sid in "abc":
            self.prompt(sid + "t", 1, "tiny")
        self.assertEqual(self.keys(), set())

    def test_short_prompt_with_skill_is_a_workflow(self):
        self.prompt("s", 1, "hi", skills=["sk1"])
        self.assertEqual(self.keys(), {("workflow", "sk1")})

    def test_first_skill_by_ts_and_failed_load_skipped(self):
        self.prompt("s", 1, LONG, skills=["first", "second"])
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, prompt_idx, failed) VALUES ('s', ?, 'zero', 1, 1)",
                          (stamp(1, -5),))
        self.assertEqual(self.keys(), {("workflow", "first")})

    def test_main_thread_skill_beats_earlier_subagent_skill(self):
        self.prompt("s", 1, LONG, skills=["main-skill"])
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, prompt_idx, agent_id, failed) "
                          "VALUES ('s', ?, 'sub-skill', 1, 'ag1', 0)", (stamp(1, -5),))
        self.assertEqual(self.keys(), {("workflow", "main-skill")})

    def test_skill_in_subagent_counts(self):
        self.prompt("s", 1, LONG, sub_skills=["agent-skill"])
        self.assertEqual(self.keys(), {("workflow", "agent-skill")})

    def test_task_group_limits(self):
        for i, sid in enumerate(("a", "a", "b")):
            self.prompt(sid, i + 1, "Refactor the billing module part %d" % i)
        self.assertEqual(self.keys(), {("task", "refactor the billing module part")})
        self.conn.execute("DELETE FROM prompts WHERE session_id = 'b'")
        self.assertEqual(self.keys(), set())  # two prompts
        self.conn.execute("INSERT INTO prompts VALUES ('a', 3, ?, 'Refactor the billing module part 9')", (stamp(),))
        self.conn.execute("UPDATE requests SET session_id = 'a', prompt_idx = 3 WHERE session_id = 'b'")
        self.assertEqual(self.keys(), set())  # three prompts, one session

    def test_in_prompt_cost_by_hand(self):
        reqs = [dict(cost=1.0, cr=1_000_000, inp=5, w5=7, w1=11),
                dict(cost=0.5, cr=500_000),
                dict(model="claude-sonnet-4-6", cost=1.2, cr=2_000_000),
                dict(model="claude-sonnet-4-6", cost=0.4, cr=9_000_000, agent="ag1"),
                dict(model="mystery-model", cost=None, cr=100)]
        self.prompt("s", 1, LONG, skills=["sk1"], reqs=reqs)
        self.conn.execute("UPDATE requests SET cost_usd = NULL WHERE model = 'mystery-model'")
        g = self.go()["groups"][0]
        # cost 3.1; inherited: 1M*0.20/M (the whole first read) + 0.5M*0.20/M + min(2M, 1M)*0.30/M + 0 (no rate) = 0.6
        self.assertAlmostEqual(g["in_prompt_usd"], 2.5)
        self.assertEqual((g["steps_median"], g["subagent_requests"]), (4, 1))
        self.assertEqual(g["start_context_median"], 5 + 1_000_000 + 7 + 11)
        self.assertIn("mystery-model", self.go()["unpriced"])

    def test_first_request_pays_only_its_non_read_cost(self):
        self.prompt("s", 1, LONG, skills=["sk1"], reqs=[dict(cost=0.3 + 0.2, cr=1_000_000)])  # 0.2 is the read at 0.20/M
        self.assertAlmostEqual(self.go()["groups"][0]["in_prompt_usd"], 0.3)

    def test_inherited_share_never_exceeds_stored_cost(self):
        # stored cost was priced at ingest; a higher current cache-read rate must not make in_prompt negative
        rows = [(None, "m", 0.10, 0, 1_000_000, 0, 0), (None, "m", 0.10, 0, 1_000_000, 0, 0)]
        got = patterns._measure(rows, lambda m: 1e-6)  # 1.00 per request at the current rate, 0.10 stored
        self.assertGreaterEqual(got["in_prompt"], 0.0)
        self.assertAlmostEqual(got["in_prompt"], 0.0)

    def test_group_fields_and_rank(self):
        self.prompt("a", 1, LONG, skills=["cheap"], reqs=[dict(cost=1.0)])
        self.prompt("a", 2, LONG, skills=["dear"], reqs=[dict(cost=2.0)])
        self.prompt("b", 1, LONG, skills=["dear"], reqs=[dict(cost=4.0), dict(cost=2.0)])
        self.prompt("c", 1, LONG, skills=["dear"], reqs=[dict(cost=0.5, agent="ag1")])  # no main-thread request
        (self.facets / "a.json").write_text('{"outcome": "achieved"}')
        (self.facets / "b.json").write_text('{"outcome": "achieved"}')
        groups = self.go()["groups"]
        self.assertEqual([g["key"] for g in groups], ["dear", "cheap"])
        g = groups[0]
        self.assertEqual((g["prompts"], g["sessions"]), (3, 3))
        self.assertAlmostEqual(g["in_prompt_usd"], 8.5)
        self.assertEqual((g["in_prompt_low"], g["in_prompt_median"], g["in_prompt_high"]), (0.5, 2.0, 6.0))
        self.assertEqual(g["steps_median"], 1)  # steps 1, 2, 0
        self.assertEqual(g["subagent_requests"], 1)
        self.assertEqual(g["start_context_median"], 10)  # the prompt with no main-thread request has none
        self.assertEqual(g["outcomes"], {"achieved": 2})
        self.assertEqual(g["skills"], ["dear"])
        self.assertEqual(g["example"], LONG)
        self.assertEqual(groups[1]["start_context_median"], 10)

    def test_equal_cost_ranks_by_key(self):
        self.prompt("a", 1, LONG, skills=["zz"])
        self.prompt("b", 1, LONG, skills=["aa"])
        self.assertEqual([g["key"] for g in self.go()["groups"]], ["aa", "zz"])

    def test_start_context_none_when_no_main_thread(self):
        self.prompt("a", 1, LONG, skills=["sk"], reqs=[dict(agent="ag1")])
        self.assertIsNone(self.go()["groups"][0]["start_context_median"])

    def test_prompt_crossing_the_bound_keeps_all_requests(self):
        since = (tz.now().date() - timedelta(days=1)).isoformat()
        bound = tz.utc_bound(since)
        edge = (datetime.strptime(bound, "%Y-%m-%dT%H:%M:%S") + timedelta(minutes=1))
        self.session("s")
        self.conn.execute("INSERT INTO prompts VALUES ('s', 1, ?, ?)", (edge.strftime("%Y-%m-%dT%H:%M:%S.000Z"), LONG))
        for i, cost in enumerate((1.0, 2.0)):  # the first request is before the bound, the second after
            self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, cache_read, "
                              "cache_write_5m, cache_write_1h, cost_usd) VALUES ('s', ?, ?, 'claude-opus-5-5', 1, 1, 0, 0, 0, ?)",
                              (f"x{i}", (edge + timedelta(minutes=i - 3)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), cost))
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, prompt_idx, failed) VALUES ('s', ?, 'sk', 1, 0)", (stamp(),))
        g = self.go(since=since)["groups"][0]
        self.assertEqual((g["steps_median"], g["in_prompt_usd"]), (2, 3.0))

    def test_default_window_is_14_days(self):
        self.prompt("old", 1, LONG, days=15, skills=["old"])
        self.prompt("new", 1, LONG, days=13, skills=["new"])
        self.assertEqual(self.keys(), {("workflow", "new")})

    def test_since_bound_excludes_older_prompts(self):
        self.prompt("a", 1, LONG, days=5, skills=["old"])
        self.prompt("b", 1, LONG, days=1, skills=["new"])
        since = (tz.now().date() - timedelta(days=2)).isoformat()
        self.assertEqual(self.keys(since=since), {("workflow", "new")})


class PrivacyLevelTest(Base):
    def seed(self):
        self.prompt("a", 1, CANARY + " deploy it", skills=["acme-deploy"], reqs=[dict(cost=2.0)])
        self.prompt("b", 1, "<local-command-stdout>" + CANARY, skills=["machine-skill"])
        self.prompt("c", 1, LONG, skills=["bench-skill"], project="-home-u-tokscope-bench-2")
        for i, sid in enumerate("def"):
            self.prompt(sid, 1, "CANARY-TASK write the weekly report %d" % i)

    def test_machine_prompt_and_bench_absent_at_every_level(self):
        self.seed()
        for level in ("full", "redacted", "numbers"):
            blob = json.dumps(self.go(level))
            self.assertNotIn("machine-skill", blob, level)
            self.assertNotIn("bench-skill", blob, level)

    def test_workflow_numbers_equal_at_full_and_redacted(self):
        self.seed()
        strip = lambda g: {k: v for k, v in g.items() if k != "example"}  # noqa: E731
        full = [strip(g) for g in self.go("full")["groups"] if g["kind"] == "workflow"]
        redacted = [strip(g) for g in self.go("redacted")["groups"]]
        self.assertEqual(full, redacted)
        self.assertEqual(redacted[0]["key"], "acme-deploy")

    def test_numbers_aliases_skills_and_levels_have_no_task_groups_or_text(self):
        self.seed()
        full = self.go("full")
        self.assertIn(("task", "canary-task write the weekly report"), {(g["kind"], g["key"]) for g in full["groups"]})
        numbers = self.go("numbers")
        self.assertEqual([g["key"] for g in numbers["groups"]][0][:6], "skill-")
        for level in ("redacted", "numbers"):
            result = self.go(level)
            self.assertEqual({g["kind"] for g in result["groups"]}, {"workflow"})
            self.assertTrue(all(g["example"] is None for g in result["groups"]))
            blob = json.dumps(result).lower()
            self.assertNotIn("canary", blob)
            self.assertNotIn("weekly report", blob)

    def test_facets_read_only_at_full(self):
        self.prompt("a", 1, "x", skills=["acme-deploy"])
        (self.facets / "a.json").write_text('{"outcome": "achieved"}')
        self.assertEqual(self.go("full")["groups"][0]["outcomes"], {"achieved": 1})
        for level in ("redacted", "numbers"):
            with mock.patch.object(patterns, "_outcome", side_effect=AssertionError("facet read")):
                self.assertEqual(self.go(level)["groups"][0]["outcomes"], {})

    def test_invalid_level(self):
        with self.assertRaises(ValueError):
            patterns.run(self.db, "2000-01-01T00:00:00", "bogus")


class CliTest(Base):
    def cli(self, *argv):
        self.conn.commit()
        self.conn.close()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "DB", self.db), mock.patch.object(sys, "argv", ["tokscope", "patterns", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main()
                code = 0
            except SystemExit as e:
                code = e.code
        self.conn = connect(self.db)
        return code, out.getvalue(), err.getvalue()

    def test_json_stdout_is_only_json_and_notes_go_to_stderr(self):
        self.prompt("a", 1, LONG, skills=["sk1"], reqs=[dict(model="mystery-model")])
        self.conn.execute("UPDATE requests SET cost_usd = NULL")
        code, out, err = self.cli("--format", "json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["key"], "sk1")
        self.assertIn("API-eq", err)
        self.assertIn("unpriced", err)

    def test_table_with_groups_and_notes_on_stdout(self):
        self.prompt("a", 1, LONG, skills=["sk1"])
        code, out, err = self.cli()
        self.assertEqual(code, 0)
        self.assertIn("API-eq $", out)
        self.assertIn("sk1", out)
        self.assertIn("e.g. " + LONG, out)
        self.assertIn("API-eq = these tokens", out)
        self.assertEqual(err, "")

    def test_no_groups_on_a_fresh_database(self):
        fresh = Path(tempfile.mkdtemp()) / "fresh.db"
        self.db = fresh
        self.conn = connect(fresh)
        code, out, _ = self.cli("--format", "json", "--privacy", "numbers")
        self.assertEqual((code, json.loads(out)), (0, []))
        code, out, _ = self.cli()
        self.assertEqual(code, 0)
        self.assertIn("no prompt groups", out)
        self.assertIn("tokscope ingest", out)

    def test_missing_database_is_not_created(self):
        absent = Path(tempfile.mkdtemp()) / "absent.db"
        out = io.StringIO()
        with mock.patch.object(cli, "DB", absent), mock.patch.object(sys, "argv", ["tokscope", "patterns", "--format", "json"]), \
                contextlib.redirect_stdout(out):
            cli.main()
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertFalse(absent.exists())

    def test_bad_date_and_bad_level(self):
        code, out, err = self.cli("--since", "yesterday")
        self.assertEqual(code, "tokscope: bad date 'yesterday', use YYYY-MM-DD")
        code, _, err = self.cli("--privacy", "everything")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_default_window_and_since_override(self):
        self.prompt("old", 1, LONG, days=15, skills=["old"])
        self.prompt("new", 1, LONG, days=13, skills=["new"])
        self.assertEqual([g["key"] for g in json.loads(self.cli("--format", "json")[1])], ["new"])
        since = (tz.now().date() - timedelta(days=20)).isoformat()
        self.assertEqual({g["key"] for g in json.loads(self.cli("--format", "json", "--since", since)[1])},
                         {"old", "new"})

    def test_privacy_level_through_the_command(self):
        self.prompt("a", 1, CANARY + " deploy it", skills=["acme-deploy"])
        _, out, _ = self.cli("--format", "json", "--privacy", "redacted")
        self.assertNotIn("CANARY", out)
        self.assertEqual(json.loads(out)[0]["key"], "acme-deploy")


class RenderTest(unittest.TestCase):
    def test_table_handles_none(self):
        g = {"kind": "workflow", "key": "k", "prompts": 1, "sessions": 1, "in_prompt_usd": 1.0, "in_prompt_low": 1.0,
             "in_prompt_median": 1.0, "in_prompt_high": 1.0, "steps_median": 0, "subagent_requests": 0,
             "skills": [], "start_context_median": None, "outcomes": {}, "example": None}
        text = patterns.to_table({"groups": [g], "unpriced": ""})
        self.assertEqual(len(text.splitlines()), 2)
        self.assertEqual(json.loads(patterns.to_json({"groups": [g]}))[0]["key"], "k")


if __name__ == "__main__":
    unittest.main()
