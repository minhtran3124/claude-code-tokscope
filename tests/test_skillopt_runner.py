import json
import tempfile
import unittest
from pathlib import Path

from tokscope.experiments.skillopt import grade


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


if __name__ == "__main__":
    unittest.main()
