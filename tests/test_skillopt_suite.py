import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.core import ingest, skills
from tokscope.experiments.skillopt import suite

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "skillopt-suite-session.jsonl"
CHECK = {"type": "answer_regex", "pattern": "ok"}


def case(cid, **kw):
    return {"id": cid, "prompt": f"prompt {cid}", "checks": [CHECK], **kw}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.proj = self.tmp / "proj"
        self.skill = self.proj / ".claude" / "skills" / "demo"
        (self.skill / "evals").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("---\nname: demo\ndescription: Summarize notes\n---\nbody\n")
        (self.skill / "ref.md").write_text("ref\n")
        for name, value in (("TOKSCOPE_HOME", self.tmp / "data"), ("HOME", self.tmp / "home")):
            p = mock.patch.dict(os.environ, {name: str(value)})
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("os.getcwd", return_value=str(self.proj))
        p.start()
        self.addCleanup(p.stop)

    def write(self, data, name="evals.json"):
        (self.skill / "evals" / name).write_text(json.dumps(data))

    def many(self, n):
        self.write({"evals": [case(f"c{i}") for i in range(n)], "checks": []})
        return suite.load("demo")


class CheckTest(Base):
    def test_three_faults_are_three_problems(self):
        self.write({"evals": [case("a", checks=[{"type": "answer_regex", "pattern": ""}]),
                              case("b", files=["evals/nope.txt"]), case("b")]})
        s = suite.load("demo")
        self.assertEqual(len(s.problems), 3, s.problems)
        self.assertTrue(s.refused)
        self.assertTrue(any("pattern" in p for p in s.problems))
        self.assertTrue(any("does not exist" in p for p in s.problems))
        self.assertTrue(any("duplicate" in p for p in s.problems))

    def test_no_checks_no_prompt_and_escaping_paths(self):
        self.write({"evals": [{"id": "a", "prompt": "p"}, {"id": "b", "checks": [CHECK]},
                              case("c", files=["../x", "/etc/passwd"])]})
        s = suite.load("demo")
        self.assertTrue(any(p.startswith("case a") and "no machine checks" in p for p in s.problems))
        self.assertTrue(any(p.startswith("case b") and "no prompt" in p for p in s.problems))
        self.assertEqual(sum("outside the skill folder" in p for p in s.problems), 2)

    def test_suite_level_checks_cover_cases(self):
        self.write({"evals": [{"id": "a", "prompt": "p"}], "checks": [CHECK]})
        self.assertEqual(suite.load("demo").problems, [])

    def test_load_errors(self):
        (self.skill / "evals" / "evals.json").write_text("{nope")
        with self.assertRaises(ValueError):
            suite.load("demo")
        self.write([1])
        with self.assertRaises(ValueError):
            suite.load("demo")
        with self.assertRaises(ValueError):
            suite.load("nothere")
        with self.assertRaises(ValueError):
            suite.load("plug:demo")


class SplitTest(Base):
    def test_same_holdout_and_no_rewrite(self):
        s = self.many(6)
        first = suite.split(s)
        before = (self.skill / "evals" / "evals.json").read_bytes()
        mtime = (self.skill / "evals" / "evals.json").stat().st_mtime_ns
        self.assertEqual(suite.split(suite.load("demo")), first)
        self.assertEqual((self.skill / "evals" / "evals.json").read_bytes(), before)
        self.assertEqual((self.skill / "evals" / "evals.json").stat().st_mtime_ns, mtime)

    def test_holdout_size(self):
        for n in range(2, 11):
            dev, hold = suite.split(self.many(n), write=False)
            self.assertEqual(len(hold), math.ceil(n / 3))
            self.assertGreaterEqual(len(hold), n / 3)
            self.assertEqual(sorted(dev + hold), sorted(f"c{i}" for i in range(n)))

    def test_split_is_written(self):
        s = self.many(4)
        _, hold = suite.split(s)
        data = json.loads((self.skill / "evals" / "evals.json").read_text())
        self.assertEqual(data["split"], {"hash": suite.suite_hash(data), "holdout": hold})
        self.assertEqual(list(data)[:2], ["evals", "checks"])

    def test_edit_resplits(self):
        suite.split(self.many(5))
        data = json.loads((self.skill / "evals" / "evals.json").read_text())
        old = data["split"]["hash"]
        data["evals"][0]["prompt"] = "changed"
        self.write(data)
        s = suite.load("demo")
        self.assertNotEqual(suite.suite_hash(s.data), old)
        suite.split(s)
        self.assertNotEqual(json.loads((self.skill / "evals" / "evals.json").read_text())["split"]["hash"], old)

    def test_hand_chosen_holdout_is_kept(self):
        s = self.many(6)
        _, seeded = suite.split(s, write=False)
        other = sorted(set(f"c{i}" for i in range(6)) - set(seeded))[:2]
        data = dict(s.data)
        data["split"] = {"hash": suite.suite_hash(data), "holdout": other}
        self.write(data)
        self.assertEqual(suite.split(suite.load("demo"))[1], other)

    def test_stored_holdout_with_unknown_id_is_a_problem(self):
        s = self.many(4)
        data = dict(s.data)
        data["split"] = {"hash": suite.suite_hash(data), "holdout": ["ghost"]}
        self.write(data)
        self.assertTrue(any("ghost" in p for p in suite.load("demo").problems))

    def test_problems_refuse_a_split(self):
        self.write({"evals": [case("a"), {"id": "b"}]})
        with self.assertRaises(suite.Refused):
            suite.split(suite.load("demo"))
        self.assertNotIn("split", json.loads((self.skill / "evals" / "evals.json").read_text()))

    def test_one_case_cannot_split(self):
        with self.assertRaisesRegex(suite.Refused, "at least 2 cases"):
            suite.split(self.many(1))


class WorkspaceTest(Base):
    def make(self):
        fx = self.skill / "evals" / "fixtures"
        fx.mkdir()
        cases = []
        for i in range(6):
            (fx / f"fixture-MARK{i}.txt").write_text(f"data {i}\n")
            cases.append({"id": f"id-MARK{i}", "prompt": f"prompt-MARK{i}", "checks": [CHECK],
                          "files": [f"evals/fixtures/fixture-MARK{i}.txt"]})
        self.write({"evals": cases})
        return suite.load("demo")

    def test_no_holdout_material_in_workspace(self):
        s = self.make()
        dev, hold = suite.split(s)
        dest = self.tmp / "ws"
        suite.editor_workspace("demo", dest)
        blob = ""
        for p in dest.rglob("*"):
            blob += p.relative_to(dest).as_posix() + "\n"
            if p.is_file():
                blob += p.read_bytes().decode(errors="replace")
        for h in hold:
            n = h.removeprefix("id-")
            for marker in (h, f"prompt-{n}", f"fixture-{n}"):
                self.assertNotIn(marker, blob)
        for d in dev:
            n = d.removeprefix("id-")
            self.assertIn(d, blob)
            self.assertTrue((dest / "evals" / "fixtures" / f"fixture-{n}.txt").is_file())
        self.assertNotIn('"split"', blob)
        self.assertTrue((dest / "SKILL.md").is_file())

    def test_shared_fixture_is_refused(self):
        s = self.make()
        data = dict(s.data)
        for c in data["evals"]:
            c["files"] = ["evals/fixtures/fixture-MARK0.txt"]
        self.write(data)
        s = suite.load("demo")
        self.assertTrue(any("shared with holdout" in p for p in s.problems))
        with self.assertRaises(suite.Refused):
            suite.editor_workspace("demo", self.tmp / "ws2")

    def test_dest_must_be_empty(self):
        self.make()
        (self.tmp / "full").mkdir()
        (self.tmp / "full" / "x").write_text("x")
        with self.assertRaises(ValueError):
            suite.editor_workspace("demo", self.tmp / "full")

    def test_evals_changes_do_not_move_the_fingerprint(self):
        self.make()
        before = skills.fingerprint(self.skill)
        (self.skill / "evals" / "new.txt").write_text("n")
        (self.skill / "evals" / "fixtures" / "fixture-MARK0.txt").write_text("edited")
        self.assertEqual(skills.fingerprint(self.skill), before)
        (self.skill / "evals" / "new.txt").unlink()
        self.assertEqual(skills.fingerprint(self.skill), before)


class DraftTest(Base):
    def setUp(self):
        super().setUp()
        self.work = self.tmp / "work"
        self.work.mkdir()
        for name in ("notes.txt", "out.md", "other.txt"):
            (self.work / name).write_text(name)
        self.projects = self.tmp / "projects"
        (self.projects / "p").mkdir(parents=True)
        (self.projects / "p" / "sess1234abcd.jsonl").write_text(FIXTURE.read_text().replace("__DIR__", str(self.work)))
        conn = ingest.connect(paths.db())
        conn.executemany("INSERT INTO prompts VALUES (?,?,?,?)", [
            ("sess1234abcd", 1, "t", "summarize the notes file"), ("sess1234abcd", 2, "t", "now the other file"),
            ("sess1234abcd", 3, "t", ""), ("sess1234abcd", 4, "t", "failed one")])
        conn.executemany("INSERT INTO skill_calls (session_id, ts, skill, prompt_idx, failed) VALUES (?,?,?,?,?)", [
            ("sess1234abcd", "2026-11-01T10:00:01Z", "demo", 1, 0), ("sess1234abcd", "2026-11-01T10:05:01Z", "demo", 2, 0),
            ("sess1234abcd", "2026-11-01T10:06:00Z", "demo", 3, 0), ("sess1234abcd", "2026-11-01T10:07:00Z", "demo", 4, 1),
            ("sess1234abcd", "2026-11-01T10:08:00Z", "demo", None, 0), ("sess1234abcd", "2026-11-01T10:09:00Z", "other", 1, 0)])
        conn.commit()
        conn.close()

    def test_draft_from_real_calls(self):
        res = suite.draft("demo", 5, projects_dir=self.projects)
        data = json.loads((self.skill / "evals" / "evals.draft.json").read_text())
        by_prompt = {c["prompt"]: c for c in data["evals"]}
        self.assertEqual(sorted(by_prompt), ["now the other file", "summarize the notes file"])  # failed and empty skipped
        self.assertEqual(res["skipped"], 1)
        first = by_prompt["summarize the notes file"]
        self.assertEqual(first["id"], "sess1234-1")
        self.assertEqual(sorted(Path(f).name for f in first["files"]), ["notes.txt", "out.md"])  # missing.txt not copied
        for f in first["files"]:
            self.assertTrue((self.skill / f).is_file())
        self.assertFalse((self.skill / "evals" / "evals.json").exists())

    def test_draft_never_copies_secrets(self):
        (self.work / ".ssh").mkdir()
        for name in (".env", ".ssh/id_rsa", "server.pem"):
            (self.work / name).write_text("SECRET")
        extra = "".join(
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"s%d","name":"Read",'
            '"input":{"file_path":"%s/%s"}}]}}\n' % (i, self.work, n) for i, n in enumerate((".env", ".ssh/id_rsa", "server.pem")))
        tr = self.projects / "p" / "sess1234abcd.jsonl"
        lines = tr.read_text().splitlines(keepends=True)
        tr.write_text("".join(lines[:3]) + extra + "".join(lines[3:]))
        suite.draft("demo", 5, projects_dir=self.projects)
        copied = [p.name for p in (self.skill / "evals" / "fixtures").rglob("*") if p.is_file()]
        self.assertIn("notes.txt", copied)
        for bad in (".env", "id_rsa", "server.pem"):
            self.assertNotIn(bad, copied)

    def test_n_caps_and_evals_json_is_untouched(self):
        self.write({"evals": [case("keep")]})
        before = (self.skill / "evals" / "evals.json").read_bytes()
        suite.draft("demo", 1, projects_dir=self.projects)
        self.assertEqual(len(json.loads((self.skill / "evals" / "evals.draft.json").read_text())["evals"]), 1)
        self.assertEqual((self.skill / "evals" / "evals.json").read_bytes(), before)

    def test_no_calls_gives_one_case_from_the_description(self):
        conn = ingest.connect(paths.db())
        conn.execute("DELETE FROM skill_calls")
        conn.commit()
        conn.close()
        res = suite.draft("demo", 5, projects_dir=self.projects)
        self.assertEqual(len(res["cases"]), 1)
        self.assertIn("Summarize notes", res["cases"][0]["prompt"])
        self.assertIn("description", res["note"])

    def test_approve_refuses_without_checks_and_keeps_bytes(self):
        suite.draft("demo", 5, projects_dir=self.projects)
        self.write({"evals": [case("old")]})
        before = (self.skill / "evals" / "evals.json").read_bytes()
        with self.assertRaises(suite.Refused):
            suite.approve("demo")
        self.assertEqual((self.skill / "evals" / "evals.json").read_bytes(), before)

    def test_approve_copies_a_passing_draft_and_keeps_the_draft(self):
        suite.draft("demo", 5, projects_dir=self.projects)
        draft = self.skill / "evals" / "evals.draft.json"
        data = json.loads(draft.read_text())
        data["checks"] = [CHECK]
        draft.write_text(json.dumps(data))
        out = suite.approve("demo")
        self.assertEqual(json.loads(out.read_text()), data)
        self.assertTrue(draft.is_file())
        self.assertTrue((self.skill / "ref.md").is_file())

    def test_approve_refuses_to_overwrite_existing_evals_without_force(self):
        suite.draft("demo", 5, projects_dir=self.projects)
        draft = self.skill / "evals" / "evals.draft.json"
        data = json.loads(draft.read_text())
        data["checks"] = [CHECK]
        draft.write_text(json.dumps(data))
        self.write({"evals": [case("curated")]})
        before = (self.skill / "evals" / "evals.json").read_bytes()
        with self.assertRaises(suite.Refused):
            suite.approve("demo")
        self.assertEqual((self.skill / "evals" / "evals.json").read_bytes(), before)
        out = suite.approve("demo", force=True)
        self.assertEqual(json.loads(out.read_text()), data)


class CliTest(Base):
    def run_cli(self, *args):
        env = {**os.environ, "HOME": str(self.tmp / "home"), "TOKSCOPE_HOME": str(self.tmp / "data")}
        (self.tmp / "home").mkdir(exist_ok=True)
        return subprocess.run([str(ROOT / "bin" / "tokscope"), "optimize", "suite", *args],
                              cwd=self.proj, env=env, capture_output=True, text=True)

    def test_problems_exit_1(self):
        self.write({"evals": [case("a"), {"id": "b"}]})
        r = self.run_cli("demo")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("case b", r.stdout)

    def test_clean_suite_prints_split(self):
        self.many(4)
        r = self.run_cli("demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("holdout", r.stdout)
        self.assertIn("split", json.loads((self.skill / "evals" / "evals.json").read_text()))

    def test_load_errors_exit_2(self):
        self.assertEqual(self.run_cli("nothere").returncode, 2)
        (self.skill / "evals" / "evals.json").write_text("{bad")
        self.assertEqual(self.run_cli("demo").returncode, 2)

    def test_draft_and_approve(self):
        r = self.run_cli("demo", "--draft", "--n", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        draft = self.skill / "evals" / "evals.draft.json"
        self.assertTrue(draft.is_file())
        self.assertEqual(self.run_cli("demo", "--approve").returncode, 1)
        self.assertFalse((self.skill / "evals" / "evals.json").exists())
        data = json.loads(draft.read_text())
        data["checks"] = [CHECK]
        draft.write_text(json.dumps(data))
        self.assertEqual(self.run_cli("demo", "--approve").returncode, 0)
        self.assertTrue((self.skill / "evals" / "evals.json").is_file())


if __name__ == "__main__":
    unittest.main()
