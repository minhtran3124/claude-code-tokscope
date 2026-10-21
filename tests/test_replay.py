import json
import tempfile
import unittest
from pathlib import Path

from tokscope import replay
from tokscope.ingest import connect


def line(rec):
    return json.dumps(rec) + "\n"


def human(text, **extra):
    return line({"type": "user", "turnOrigin": "human", "message": {"content": text}, **extra})


ANSWER = line({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}})


class ExtractTest(unittest.TestCase):
    def write(self, *lines):
        path = Path(tempfile.mkdtemp()) / "s.jsonl"
        path.write_text("".join(lines))
        return path

    def test_keeps_only_human_prompts_in_full_and_skill_commands_as_slash_lines(self):
        long_prompt = "investigate " + "x" * 500
        path = self.write(
            human("<command-name>/clear</command-name>", cwd="/repo", timestamp="2026-10-19T02:00:00Z"),
            human(long_prompt), ANSWER,
            line({"type": "user", "turnOrigin": "task_notification", "message": {"content": "<task-notification>x"}}),
            line({"type": "user", "toolUseResult": {}, "message": {"content": [{"type": "tool_result"}]}}),
            human("<command-name>/uat</command-name><command-args>run it</command-args>"), ANSWER,
        )
        groups, cwd, first_ts = replay.extract_prompts(path)
        self.assertEqual([g["text"] for g in groups], [long_prompt, "/uat run it"])  # full text, not the snippet
        self.assertEqual((cwd, first_ts), ("/repo", "2026-10-19T02:00:00Z"))

    def test_prompts_sent_before_any_answer_are_one_turn(self):
        # 2026-10-19 session 33211663: a typo, Esc, a bare URL, then the real ask, all before the first answer
        path = self.write(
            human("investigate issuse"), human("[Request interrupted by user]"), human("https://dd/monitor"),
            human("investigate issue https://dd/monitor"), ANSWER, human("review sentry"), ANSWER,
        )
        groups, _, _ = replay.extract_prompts(path)
        self.assertEqual([g["orig"] for g in groups], [[1, 2, 3], [4]])
        self.assertEqual(groups[0]["text"], "investigate issuse\n\nhttps://dd/monitor\n\ninvestigate issue https://dd/monitor")


class CommandTest(unittest.TestCase):
    def test_first_turn_names_the_session_and_later_turns_resume_it(self):
        first = replay.build_cmd("claude", "p1", "sid", True)
        later = replay.build_cmd("claude", "p2", "sid", False)
        self.assertEqual(first[first.index("--session-id") + 1], "sid")
        self.assertNotIn("--resume", first)
        self.assertEqual(later[later.index("--resume") + 1], "sid")

    def test_replays_can_never_write(self):
        cmd = replay.build_cmd("claude", "p", "sid", True)
        allowed = cmd[cmd.index("--allowedTools") + 1:cmd.index("--disallowedTools")]
        for tool in ("Edit", "Write", "NotebookEdit", "Bash"):
            self.assertNotIn(tool, allowed)
        self.assertFalse([t for t in allowed if t.startswith("Bash(") and any(w in t for w in ("push", "commit", "rm", "gh"))])
        denied = cmd[cmd.index("--disallowedTools") + 1:]
        self.assertIn("mcp__plugin_sentry_sentry__execute_sentry_tool", denied)
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "default")


class DiffTest(unittest.TestCase):
    def test_a_run_that_replayed_merged_prompts_one_by_one_is_summed_over_the_group(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "projects" / "p").mkdir(parents=True)
        (tmp / "projects" / "p" / "orig.jsonl").write_text(
            human("a") + human("b") + ANSWER + human("c") + ANSWER)
        db = tmp / "t.db"
        conn = connect(db)
        conn.executescript(replay.REPLAY_SCHEMA)
        # original: prompts 1+2 were one turn (all tokens on idx 2), prompt 3 its own
        rows = [("orig", "o1", 2, 4000), ("orig", "o2", 3, 2000),
                ("old", "a1", 1, 1000), ("old", "a2", 2, 2000), ("old", "a3", 3, 1000),   # replayed one by one
                ("new", "b1", 1, 2500), ("new", "b2", 2, 1500)]                           # replayed merged
        conn.executemany("INSERT INTO requests (session_id, request_key, prompt_idx, input, output, cache_read, "
                         "cache_write_5m, cache_write_1h) VALUES (?,?,?,?,0,0,0,0)", rows)
        conn.execute("INSERT INTO replay_runs VALUES ('r0','orig',0,'old','sha','2026-10-20T01',10,3,0,1,0.5,'done')")
        conn.execute("INSERT INTO replay_runs VALUES ('r1','orig',1,'new','sha','2026-10-20T02',10,2,0,0,0.5,'done')")
        conn.executemany("INSERT INTO replay_turns (run_id, turn, prompt, orig_idx) VALUES (?,?,?,?)",
                         [("r0", 1, "a", None), ("r0", 2, "b", None), ("r0", 3, "c", None),
                          ("r1", 1, "a\n\nb", "1,2"), ("r1", 2, "c", "3")])
        conn.commit()
        out = replay.diff(db, "orig", projects_dir=tmp / "projects")
        group = next(l for l in out.splitlines() if l.startswith("1,2 "))
        cells = [c for c in group.split() if c.endswith("K")]
        self.assertEqual(cells[:3], ["4.0K", "3.0K", "2.5K"])  # original; old run 1.0K+2.0K; merged run
        self.assertIn("1 permission denials", out)


if __name__ == "__main__":
    unittest.main()
