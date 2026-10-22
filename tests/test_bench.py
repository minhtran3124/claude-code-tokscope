import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tokscope.experiments import bench
from tokscope.core.ingest import connect

TASK = json.loads((Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "grader-plain.json").read_text())


class GradeTest(unittest.TestCase):
    def test_passes_only_when_the_held_connection_during_the_wait_is_named(self):
        hit = "The session keeps its pooled connection checked out while asyncio.sleep waits up to 11.75s."
        self.assertTrue(bench.grade(TASK, hit))
        # a plausible but different finding must not pass
        self.assertFalse(bench.grade(TASK, "stripe.Customer.create is a blocking sync call inside an async function."))
        self.assertFalse(bench.grade(TASK, ""))

    def test_function_names_alone_do_not_satisfy_the_wait_pattern(self):
        # create_or_retrieve_customer and await appear in every answer; they once matched "retr" and "wait"
        text = "create_or_retrieve_customer holds a pool connection; await db.execute(...) blocks."
        self.assertFalse(bench.grade(TASK, text))

    def test_every_variant_prompt_names_its_model(self):
        for name, variant in TASK["variants"].items():
            self.assertIn(f'model "{variant["model"]}"', TASK["prompt"].format(**variant), name)


class WindowGradeTest(unittest.TestCase):
    TASK = json.loads((Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "grader-window.json").read_text())

    def test_passes_when_one_finding_names_the_expired_read(self):
        hit = ("profile.py:860 deactivate_algo_broker_subscriptions logs customer_data.id after await db.commit(); "
               "expire_on_commit=True expires it, so the access triggers a lazy reload that raises MissingGreenlet.")
        self.assertTrue(bench.grade(self.TASK, hit))

    def test_fails_when_the_words_only_appear_in_separate_findings(self):
        # a whole-file review mentions commit and the function elsewhere; that alone must not pass
        spread = ("1. deactivate_algo_broker_subscriptions swallows every exception.\n" + "x" * 1200 +
                  "\n2. update_profile calls db.commit() twice.\n" + "y" * 1200 +
                  "\n3. get_profile could refresh the cache more often.")
        self.assertFalse(bench.grade(self.TASK, spread))


class SnapshotNameTest(unittest.TestCase):
    def test_snapshot_path_does_not_leak_the_task_name(self):
        # 2026-10-20: a reviewer quoted "the bug this snapshot is named for" from .../snapshots/profile-expired-id/
        path = str(bench.snapshot_dir("/r", "62e124e04c1e5708e60b06d7a4485911aea2df05"))
        self.assertEqual(path, "/r/bench/snapshots/s-62e124e04c")
        for word in ("profile", "expired", "stripe", "pool"):
            self.assertNotIn(word, path)


class ScheduleTest(unittest.TestCase):
    def test_variants_interleave_so_cache_warmth_is_shared(self):
        # the order flips each round, so the cold-cache first run is not always the same variant's
        self.assertEqual(bench.schedule(["a", "b"], 3), [(0, "a"), (0, "b"), (1, "b"), (1, "a"), (2, "a"), (2, "b")])


class DiffTest(unittest.TestCase):
    def test_splits_cost_by_owner_and_counts_passes_per_variant(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        conn = connect(db)
        for run_id, variant, passed, sid in (("r1", "a", 1, "s1"), ("r2", "a", 0, "s2"), ("r3", "b", 1, "s3")):
            bench.save_run(conn, {"run_id": run_id, "task": "t", "variant": variant, "run_idx": 0, "session_id": sid,
                                  "passed": passed, "is_error": 0, "duration_s": 10.0, "reported_cost": 1.0})
        rows = [("s1", "k1", None, 1.0), ("s1", "k2", "ag", 2.0), ("s2", "k3", None, 3.0), ("s3", "k4", "ag", 0.5)]
        conn.executemany(
            "INSERT INTO requests (session_id, request_key, agent_id, cost_usd, output, model) VALUES (?,?,?,?,10,'m')", rows)
        conn.commit()
        out = bench.diff(db, "t").splitlines()
        a = next(line for line in out if line.startswith("a "))
        b = next(line for line in out if line.startswith("b "))
        self.assertIn("1/2", a)
        self.assertIn("3.000 [3.000–3.000]", a)  # both runs total $3
        self.assertIn("1/1", b)
        self.assertIn("0.500", b)


if __name__ == "__main__":
    unittest.main()
