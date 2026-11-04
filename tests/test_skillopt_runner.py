import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope.core import skills
from tokscope.experiments.skillopt import grade, sandbox

ROOT = Path(__file__).resolve().parent.parent


def ev(**kw):
    return json.dumps(kw)


def use(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


RESULT = {"type": "result", "result": "All done: wrote out.md", "is_error": False}


class GradeTest(unittest.TestCase):
    def setUp(self):
        self.sb = Path(tempfile.mkdtemp())
        (self.sb / "out.md").write_text("intro\n# Title\nbody\n")
        self.events = [use("Read", file_path="a.txt"), use("Write", file_path="out.md"), RESULT]

    def run_checks(self, checks, events=None):
        return grade.grade(events or self.events, self.sb, checks)

    def test_all_six_types_pass_with_evidence(self):
        checks = [{"type": "answer_regex", "pattern": "wrote out"},
                  {"type": "file_exists", "path": "out.md"},
                  {"type": "file_contains", "path": "out.md", "pattern": "^# Title"},
                  {"type": "tool_called", "tool": "Write", "input_contains": "out.md"},
                  {"type": "tool_order", "tools": ["Read", "Write"]},
                  {"type": "no_permission_denials", "safety": True}]
        g = self.run_checks(checks)
        self.assertEqual((g["status"], g["passed"], g["total"], g["safety_failed"]), ("ok", 6, 6, 0))
        self.assertEqual(len(g["expectations"]), 6)
        for e in g["expectations"]:
            self.assertTrue(e["evidence"])
        ev_ = [e["evidence"] for e in g["expectations"]]
        self.assertIn("wrote out", ev_[0])
        self.assertIn("# Title", ev_[2])
        self.assertIn("out.md", ev_[3])
        self.assertIn("Read > Write", ev_[4])
        self.assertIn("0 denials", ev_[5])

    def test_failures_quote_what_was_seen(self):
        g = self.run_checks([{"type": "answer_regex", "pattern": "zzz"},
                             {"type": "file_exists", "path": "nope.md"},
                             {"type": "tool_order", "tools": ["Write", "Read"]},
                             {"type": "tool_called", "tool": "Bash"}])
        self.assertEqual(g["passed"], 0)
        self.assertIn("All done", g["expectations"][0]["evidence"])
        self.assertIn("missing", g["expectations"][1]["evidence"])
        self.assertIn("Read > Write", g["expectations"][2]["evidence"])
        self.assertIn("Read, Write", g["expectations"][3]["evidence"])

    def test_denials_and_safety(self):
        events = [{"type": "system", "subtype": "permission_denied", "tool_name": "Bash"},
                  dict(RESULT, permission_denials=[{"tool_name": "Write"}])]
        g = self.run_checks([{"type": "no_permission_denials", "safety": True}], events)
        self.assertEqual((g["passed"], g["safety_failed"]), (0, 1))
        self.assertIn("Bash, Write", g["expectations"][0]["evidence"])

    def test_invalid_when_result_is_error(self):
        err = {"type": "result", "subtype": "error_max_turns", "result": "All done: wrote out.md", "is_error": True}
        g = self.run_checks([{"type": "file_exists", "path": "out.md"}], self.events[:2] + [err])
        self.assertEqual(g["status"], "INVALID")
        self.assertIn("error_max_turns", g["reason"])
        self.assertEqual(g["expectations"], [])

    def test_invalid_without_result(self):
        g = self.run_checks([{"type": "file_exists", "path": "out.md"}], self.events[:2])
        self.assertEqual(g["status"], "INVALID")
        self.assertEqual(g["expectations"], [])
        self.assertNotIn("passed", g)
        self.assertNotIn("total", g)

    def test_path_escape_fails(self):
        (self.sb.parent / "secret.txt").write_text("x")
        for path in ("../secret.txt", str(self.sb.parent / "secret.txt")):
            g = self.run_checks([{"type": "file_exists", "path": path}])
            self.assertEqual(g["passed"], 0, path)
            self.assertIn("leaves the sandbox", g["expectations"][0]["evidence"])

    def test_check_shape_errors(self):
        for bad in ({"type": "nope"}, {"type": "file_exists"}, {"type": "answer_regex", "pattern": "("},
                    {"type": "tool_order", "tools": "Read"}):
            with self.assertRaises(ValueError):
                grade.check_shape(bad)
        grade.check_shape({"type": "no_permission_denials"})

    def test_parse_skips_noise(self):
        self.assertEqual(len(grade.parse(["not json", ev(type="result"), "[1]", ""])), 1)

    def test_write(self):
        d = Path(tempfile.mkdtemp())
        grade.write(d, {"status": "INVALID"})
        self.assertEqual(json.loads((d / "grading.json").read_text())["status"], "INVALID")


# stands in for claude -p: loads ./.claude/skills/<skill>/SKILL.md, writes out.md in its cwd, answers in stream-json
FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ["FAKE_ARGS"]).write_text(json.dumps(sys.argv[1:]))
say = lambda ev: print(json.dumps(ev), flush=True)
cwd = os.getcwd()
say({"type": "system", "subtype": "init", "model": "claude-sonnet-5-5", "plugins": [{"name": "p1"}, {"name": "p2"}]})
skill = Path(".claude/skills/demo/SKILL.md")
if skill.exists() and not os.environ.get("FAKE_NO_CALL"):
    text = skill.read_text().split("---\\n", 2)[2].strip()  # the body, as Claude Code puts it in the context
    if os.environ.get("FAKE_OTHER_TEXT"):
        text = "SOMETHING ELSE"
    say({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": "demo"}}]}})
    block = [{"type": "tool_result", "tool_use_id": "t1", "content": "Launching skill: demo"}]
    if not os.environ.get("FAKE_NO_TEXT"):
        block.append({"type": "text", "text": "Base directory for this skill: " + cwd + "/.claude/skills/demo\\n\\n" + text})
    say({"type": "user", "message": {"content": block}})
say({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "in.txt"}}]}})
say({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "out.md"}}]}})
Path("out.md").write_text("# Title\\n" + Path("in.txt").read_text())
if not os.environ.get("FAKE_NO_RESULT"):
    say({"type": "result", "result": "done", "is_error": False, "total_cost_usd": 0.01, "num_turns": 3,
         "session_id": "s1", "usage": {"output_tokens": 5}})
"""

EVALS = {"skill_name": "demo", "checks": [{"type": "no_permission_denials", "safety": True}],
         "evals": [{"id": 1, "prompt": "do it", "files": ["evals/files/in.txt"], "checks": [
             {"type": "answer_regex", "pattern": "done"},
             {"type": "file_exists", "path": "out.md"},
             {"type": "file_contains", "path": "out.md", "pattern": "^# Title"},
             {"type": "tool_called", "tool": "Write", "input_contains": "out.md"},
             {"type": "tool_order", "tools": ["Read", "Write"]}]}]}


def make_skill(folder, marker):
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: demo\ndescription: d\n---\n{marker}\n")
    (folder / "ref.md").write_text("ref\n")


class RunnerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        fake = self.tmp / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.args = self.tmp / "args.json"
        self.home = self.tmp / "home"
        self.data = self.tmp / "data"
        self.proj = self.tmp / "proj"
        self.env = {"HOME": str(self.home), "TOKSCOPE_HOME": str(self.data), "TOKSCOPE_CLAUDE": str(fake),
                    "FAKE_ARGS": str(self.args)}
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)
        self.skill = self.proj / ".claude" / "skills" / "demo"
        make_skill(self.skill, "PROJECT-MARKER")
        (self.skill / "evals" / "files").mkdir(parents=True)
        (self.skill / "evals" / "evals.json").write_text(json.dumps(EVALS))
        (self.skill / "evals" / "files" / "in.txt").write_text("input\n")
        self.cwd = mock.patch("os.getcwd", return_value=str(self.proj))
        self.cwd.start()
        self.addCleanup(self.cwd.stop)


class SandboxTest(RunnerBase):
    def test_run_pins_project_copy_and_grades(self):
        with mock.patch.object(skills, "check_pinnable") as cp, mock.patch.object(skills, "pin") as pn:
            run = sandbox.run_case("demo", "1")
            cp.assert_not_called()
            pn.assert_not_called()
        stream = (run / "stream.jsonl").read_text()
        self.assertIn("PROJECT-MARKER", stream)
        self.assertRegex(stream, r"tokscope-skillopt-[^/]+/\.claude/skills/demo")
        g = json.loads((run / "grading.json").read_text())
        self.assertEqual((g["status"], g["passed"], g["total"]), ("ok", 6, 6))  # 5 case checks + 1 file-level
        self.assertTrue((run / "files" / "out.md").is_file())
        self.assertFalse((run / "files" / ".claude").exists())
        self.assertEqual((run / "final.md").read_text(), "done")
        meta = json.loads((run / "run.json").read_text())
        self.assertEqual(meta["fingerprint"], skills.fingerprint(self.skill))
        self.assertEqual(meta["num_turns"], 3)
        self.assertEqual(meta["usage"], {"output_tokens": 5})
        self.assertFalse(Path(meta["pinned"]).exists())  # sandbox removed
        self.assertFalse((Path(meta["pinned"]).parents[2] / "evals").exists())

    def test_child_gets_no_stdin_and_is_reaped_when_reading_fails(self):
        real, seen = subprocess.Popen, {}

        class Boom:
            def __iter__(self):
                raise RuntimeError("read failed")

            def close(self):
                pass

        def spy(*a, **kw):
            seen.update(kw)
            proc = real(*a, **kw)
            seen["proc"] = proc
            seen["out"] = proc.stdout
            proc.stdout = Boom()
            return proc

        with mock.patch.object(subprocess, "Popen", spy), self.assertRaises(RuntimeError):
            sandbox.run_case("demo", "1")
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        self.assertIsNotNone(seen["proc"].poll())  # killed and waited, not left running
        seen["out"].close()

    def test_personal_skill_of_same_name_still_runs(self):
        make_skill(self.home / ".claude" / "skills" / "demo", "PERSONAL-MARKER")
        sb = Path(tempfile.mkdtemp())
        pinned, fp = sandbox.pin_copy("demo", self.skill, sb)
        self.assertEqual(fp, skills.fingerprint(self.skill))
        self.assertIn("PROJECT-MARKER", (pinned / "SKILL.md").read_text())
        run = sandbox.run_case("demo", "1")
        stream = (run / "stream.jsonl").read_text()
        self.assertIn("PROJECT-MARKER", stream)
        self.assertRegex(stream, r"tokscope-skillopt-[^/]+/\.claude/skills/demo")

    def test_personal_only_skill_runs(self):
        personal = self.home / ".claude" / "skills" / "solo"
        make_skill(personal, "SOLO-MARKER")
        sb = Path(tempfile.mkdtemp())
        pinned, fp = sandbox.pin_copy("solo", personal, sb)
        self.assertEqual(fp, skills.fingerprint(personal))
        self.assertTrue((pinned / "SKILL.md").is_file())

    def test_pinned_copy_has_no_evals(self):
        sb = Path(tempfile.mkdtemp())
        pinned, fp = sandbox.pin_copy("demo", self.skill, sb)
        self.assertFalse((pinned / "evals").exists())
        self.assertTrue((pinned / "ref.md").is_file())
        self.assertEqual(fp, skills.fingerprint(self.skill))

    def load_of(self, **env):
        with mock.patch.dict(os.environ, env):
            run = sandbox.run_case("demo", "1")
        return json.loads((run / "run.json").read_text())["load"]

    def test_load_is_read_from_the_stream(self):
        self.assertEqual(self.load_of(), "ok")
        self.assertEqual(self.load_of(FAKE_OTHER_TEXT="1"), "other text")
        self.assertEqual(self.load_of(FAKE_NO_CALL="1"), "not loaded")
        self.assertEqual(self.load_of(FAKE_NO_TEXT="1"), "unconfirmed")

    def test_load_accepts_the_text_inside_the_tool_result(self):
        want = skills._sha(skills._body((self.skill / "SKILL.md").read_text()))
        body = (self.skill / "SKILL.md").read_text().split("---\n", 2)[2].strip()
        events = [use("Skill", skill="demo"),
                  {"type": "user", "message": {"content": [
                      {"type": "tool_result", "content": [{"type": "text", "text": "Base directory for this skill: /x\n\n" + body}]}]}}]
        self.assertEqual(sandbox.stream_load(events, "demo", want), "ok")
        self.assertEqual(sandbox.stream_load(events, "other", want), "not loaded")

    def test_no_skill_arm_pins_nothing(self):
        case, checks, _folder, fixtures = sandbox.load_case("demo", "1")
        dest = self.tmp / "out" / "0"
        run = sandbox.execute("demo", case, checks, fixtures, dest, source=None, model="haiku", budget=0.5, arm="none")
        self.assertEqual(run, dest)
        meta = json.loads((run / "run.json").read_text())
        self.assertEqual((meta["arm"], meta["load"], meta["model"], meta["fingerprint"], meta["pinned"]),
                         ("none", "n/a", "haiku", None, None))
        self.assertEqual(meta["cost_usd"], 0.01)
        for name in ("stream.jsonl", "grading.json", "run.json", "final.md"):
            self.assertTrue((run / name).is_file(), name)
        argv = json.loads(self.args.read_text())
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.5")
        for flag in ("--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertNotIn(".claude", (run / "stream.jsonl").read_text().split("Skill")[0])
        self.assertFalse(any("skills" in a for a in argv if a.startswith("/") and a != argv[0]))

    def test_model_flag_only_when_given(self):
        self.assertNotIn("--model", sandbox.command("hi", "/tmp/sb"))
        self.assertEqual(sandbox.command("hi", "/tmp/sb", model="sonnet")[-2:], ["--model", "sonnet"])
        sandbox.run_case("demo", "1")
        self.assertNotIn("--model", json.loads(self.args.read_text()))

    def test_argv_isolation_flags(self):
        sb = "/tmp/sb"
        argv = sandbox.command("hi", sb)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(argv[argv.index("--add-dir") + 1], sb)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], str(sandbox.MAX_BUDGET_USD))
        for flag in ("--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)

    def test_plugins_recorded(self):
        run = sandbox.run_case("demo", "1")
        info = json.loads((run / "plugins.json").read_text())
        self.assertEqual([p["name"] for p in info["plugins"]], ["p1", "p2"])
        self.assertTrue(info["init"])
        recorded = json.loads(self.args.read_text())
        self.assertIn("acceptEdits", recorded)

    def test_no_result_is_invalid(self):
        with mock.patch.dict(os.environ, {"FAKE_NO_RESULT": "1"}):
            run = sandbox.run_case("demo", "1")
        g = json.loads((run / "grading.json").read_text())
        self.assertEqual(g["status"], "INVALID")
        self.assertNotIn("passed", g)
        self.assertEqual(json.loads((run / "run.json").read_text())["status"], "INVALID")

    def test_missing_binary_is_invalid(self):
        with mock.patch.dict(os.environ, {"TOKSCOPE_CLAUDE": str(self.tmp / "absent")}):
            run = sandbox.run_case("demo", "1")
        g = json.loads((run / "grading.json").read_text())
        self.assertEqual(g["status"], "INVALID")
        self.assertIn("absent", g["reason"])
        self.assertEqual(json.loads((run / "plugins.json").read_text())["init"], False)

    def test_stream_write_failure_is_not_reported_as_missing_binary(self):
        class Full:
            def write(self, _):
                raise OSError(28, "No space left on device")

            def flush(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        real = Path.open

        def fake_open(path, *a, **k):
            return Full() if path.name == "stream.jsonl" else real(path, *a, **k)

        with mock.patch.object(Path, "open", fake_open):
            run = sandbox.run_case("demo", "1")
        g = json.loads((run / "grading.json").read_text())
        self.assertEqual(g["status"], "INVALID")
        self.assertIn("stream.jsonl", g["reason"])
        self.assertIn("No space left", g["reason"])

    def test_version_pins_snapshot(self):
        v = skills.fingerprint(self.skill)
        skills._snapshot("demo", v, self.skill)
        (self.skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nCHANGED-MARKER\n")
        run = sandbox.run_case("demo", "1", version=v[:6])
        stream = (run / "stream.jsonl").read_text()
        self.assertIn("PROJECT-MARKER", stream)
        self.assertNotIn("CHANGED-MARKER", stream)
        self.assertEqual(json.loads((run / "run.json").read_text())["version"], v)

    def test_load_errors(self):
        bad = [("demo", "9"), ("demo", "../x"), ("../demo", "1"), ("", "1"), ("nope", "1"), ("a:b", "1")]
        for skill, case in bad:
            with self.assertRaises(ValueError, msg=(skill, case)):
                sandbox.load_case(skill, case)
        with self.assertRaises(ValueError):
            sandbox.run_case("demo", "1", version="zzzz")

    def test_fixture_and_check_errors(self):
        path = self.skill / "evals" / "evals.json"
        for mutate in (lambda e: e["evals"][0].update(files=["../../../SKILL.md", ]),
                       lambda e: e["evals"][0].update(files=["/etc/passwd"]),
                       lambda e: e["evals"][0].update(files=["evals/files/in.txt", "ref.md", "SKILL.md", "evals/files/in.txt"]),
                       lambda e: e["evals"][0].update(checks=[{"type": "bogus"}])):
            e = json.loads(json.dumps(EVALS))
            mutate(e)
            path.write_text(json.dumps(e))
            with self.assertRaises(ValueError):
                sandbox.load_case("demo", "1")

    def test_malformed_shapes_are_value_errors(self):
        path = self.skill / "evals" / "evals.json"
        def one(**kw):
            e = json.loads(json.dumps(EVALS))
            e["evals"][0].update(kw)
            return e
        for data in ([], "x", 3, {"evals": {"a": 1}}, {**EVALS, "checks": "x"}, one(checks="x"), one(checks=5),
                     one(files="in.txt"), one(files=[3]), one(files={"a": 1})):
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError, msg=data):
                sandbox.load_case("demo", "1")


class CliTest(RunnerBase):
    def cli(self, *args, **extra):
        env = dict(os.environ, PYTHONPATH=str(ROOT), **extra)
        return subprocess.run([sys.executable, "-m", "tokscope.cli", "optimize", *args], cwd=self.proj, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_case_passes(self):
        r = self.cli("case", "demo", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("passed 6/6", r.stdout)
        self.assertIn(str(self.data / "bench" / "skillopt" / "runs" / "demo" / "1"), r.stdout)

    def test_missing_case_exits_2(self):
        r = self.cli("case", "demo", "42")
        self.assertEqual(r.returncode, 2)
        self.assertIn("tokscope:", r.stderr)
        self.assertFalse((self.data / "bench" / "skillopt").exists())

    def test_budget_flag_sets_the_cap(self):
        argv = sandbox.command("hi", "/tmp/sb", budget=0.5)
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.5")
        with self.assertRaises(ValueError):
            sandbox.run_case("demo", "1", budget=0)

    def test_cli_max_budget_usd_reaches_claude(self):
        self.assertIn("--max-budget-usd", self.cli("case", "--help").stdout)
        r = self.cli("case", "demo", "1", "--max-budget-usd", "0.25")
        self.assertEqual(r.returncode, 0, r.stderr)
        args = json.loads(self.args.read_text())
        self.assertEqual(args[args.index("--max-budget-usd") + 1], "0.25")

    def test_no_result_exits_1(self):
        r = self.cli("case", "demo", "1", FAKE_NO_RESULT="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("INVALID", r.stdout)

    def test_failed_check_exits_1_and_shows_safety(self):
        e = json.loads(json.dumps(EVALS))
        e["evals"][0]["checks"].append({"type": "file_exists", "path": "nope.md"})
        (self.skill / "evals" / "evals.json").write_text(json.dumps(e))
        r = self.cli("case", "demo", "1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("passed 6/7", r.stdout)

    def test_help_lists_version(self):
        self.assertIn("--version", self.cli("case", "--help").stdout)


@unittest.skipUnless(os.environ.get("TOKSCOPE_LIVE"), "paid live probe (under $0.01): set TOKSCOPE_LIVE=1")
class LiveIsolationTest(unittest.TestCase):
    """The real claude, not a fake: with --setting-sources project a pinned project copy is the text that loads, even
    when a personal skill has the same name. Needs one skill folder in ~/.claude/skills and a logged-in claude."""

    def test_pinned_copy_wins_over_a_personal_skill(self):
        personal = Path.home() / ".claude" / "skills"
        names = sorted(p.name for p in personal.iterdir() if (p / "SKILL.md").is_file() and not p.is_symlink()) if personal.is_dir() else []
        if not names:
            self.skipTest("no personal skill to shadow")
        name, marker = names[0], "PINNEDMARKERQX7"
        sb = Path(tempfile.mkdtemp(prefix="tokscope-live-")).resolve()
        copy = sb / ".claude" / "skills" / name
        copy.mkdir(parents=True)
        (copy / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Say the marker.\n---\nReply with exactly {marker}.\n")
        argv = sandbox.command(f"Use the {name} skill and do what it says.", sb, budget=0.5) + ["--model", "haiku"]
        out = subprocess.run(argv, cwd=sb, capture_output=True, text=True, timeout=300).stdout
        self.assertIn(marker, out)
        # the load check of the optimize loop reads the stream, so stream-json must carry the skill text
        want = skills._sha(skills._body((copy / "SKILL.md").read_text()))
        self.assertEqual(sandbox.stream_load(grade.parse(out.splitlines()), name, want), "ok")


if __name__ == "__main__":
    unittest.main()
