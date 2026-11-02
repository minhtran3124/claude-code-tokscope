"""tokscope patterns: text helpers, facets, grouping, privacy levels and the command."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope.features import patterns


class TextTest(unittest.TestCase):
    def test_mask_tokens(self):
        for raw in ("sk-ant-api03-abcDEF123", "ghp_abcdefghijklmnop", "token=abc123", "TOKEN=abc123", "api_key=zzz",
                    "Bearer abc.def", "password: hunter2", "x" * 40):
            self.assertIn("[masked]", patterns.mask(f"use {raw} now"), raw)
            self.assertNotIn(raw, patterns.mask(f"use {raw} now"))

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


if __name__ == "__main__":
    unittest.main()
