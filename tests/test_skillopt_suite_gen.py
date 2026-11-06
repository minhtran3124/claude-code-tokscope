import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope.experiments.skillopt import suite, suite_gen


def fake(result, code=0, is_error=False):
    out = json.dumps({"result": result, "is_error": is_error, "total_cost_usd": 0.12})
    return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout=out, stderr="")


class Gen(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.skill = self.tmp / "proj" / ".claude" / "skills" / "demo"
        (self.skill / "evals").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("---\nname: demo\ndescription: Summarize notes\n---\nbody\n")
        for name, value in (("TOKSCOPE_HOME", self.tmp / "data"), ("HOME", self.tmp / "home")):
            p = mock.patch.dict(os.environ, {name: str(value)})
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("os.getcwd", return_value=str(self.tmp / "proj"))
        p.start()
        self.addCleanup(p.stop)

    def test_checks_land_in_the_draft_and_evals_json_is_untouched(self):
        answer = '```json\n{"cases": {"from-description": [{"type": "answer_regex", "pattern": "summary"}]}}\n```'
        res = suite_gen.generate("demo", run=fake(answer))
        self.assertEqual(res["problems"], [])
        self.assertEqual(res["cost"], 0.12)
        draft = json.loads((self.skill / "evals" / "evals.draft.json").read_text())
        self.assertEqual(draft["evals"][0]["checks"], [{"type": "answer_regex", "pattern": "summary"}])
        self.assertFalse((self.skill / "evals" / "evals.json").exists())

    def test_bad_checks_are_dropped_and_the_case_stays_a_problem(self):
        answer = json.dumps({"cases": {"from-description": [{"type": "nope"}, {"type": "file_exists"}]}})
        res = suite_gen.generate("demo", run=fake(answer))
        self.assertEqual(res["dropped"], 2)
        self.assertTrue(any("no machine checks" in p for p in res["problems"]))

    def test_a_failed_call_or_a_non_json_answer_is_a_value_error(self):
        with self.assertRaises(ValueError):
            suite_gen.generate("demo", run=fake("budget exceeded", code=1, is_error=True))
        with self.assertRaises(ValueError):
            suite_gen.generate("demo", run=fake("sorry, no"))

    def test_the_call_has_no_tools_and_a_cost_cap(self):
        argv = suite_gen.command("p", 0.5, "sonnet")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.5")
        self.assertNotIn("--dangerously-skip-permissions", argv)

    def test_friendly_messages(self):
        self.assertIn("no eval suite", suite_gen.friendly("create-pr: no /x/evals/evals.json")[0])
        self.assertIn("machine checks", suite_gen.friendly("suite has problems: case 1: no machine checks")[0])
        self.assertEqual(suite_gen.friendly("odd")[0], "odd")


if __name__ == "__main__":
    unittest.main()
