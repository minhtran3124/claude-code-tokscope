import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.core import ingest as ingest_mod
from tokscope.core.ingest import connect, ingest, open_db
from tokscope.core.skills import canonical_name, loaded_text_hash
from tokscope.core.pricing import cost_usd

PHASES = paths.ASSETS / "phases.json"
SID = "s1"


def human(text, ts="2026-10-01T00:00:00Z"):
    return {"type": "user", "turnOrigin": "human", "timestamp": ts, "message": {"role": "user", "content": text}}


def result(tool_use_id, content):
    return {"type": "user", "toolUseResult": {}, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}]}}


def notification(text):
    return {"type": "user", "turnOrigin": "task_notification", "message": {"role": "user", "content": text}}


def assistant(req, out=10, tools=(), model="claude-opus-5-5", cw5=0, cw1=0):
    content = [{"type": "tool_use", "id": tid, "name": name, "input": inp} for tid, name, inp in tools]
    usage = {
        "input_tokens": 1, "output_tokens": out, "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": cw5 + cw1,
        "cache_creation": {"ephemeral_5m_input_tokens": cw5, "ephemeral_1h_input_tokens": cw1},
    }
    return {"type": "assistant", "requestId": req, "timestamp": "2026-10-01T00:00:01Z",
            "message": {"id": "m" + req, "model": model, "content": content, "usage": usage}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # skill names resolve against ~/.claude; an empty home keeps the parse the same on every machine
        home = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "home")})
        home.start()
        self.addCleanup(home.stop)
        canonical_name.cache_clear()
        self.project = self.tmp / "projects" / "proj"
        self.project.mkdir(parents=True)
        self.db = self.tmp / "t.db"

    def write_main(self, records):
        (self.project / f"{SID}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    def write_agent(self, agent_id, meta, records):
        d = self.project / SID / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"agent-{agent_id}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        (d / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))

    def run_ingest(self):
        return ingest(self.db, PHASES, projects_dir=self.tmp / "projects", log=lambda *_: None)

    def rows(self, sql):
        return sqlite3.connect(self.db).execute(sql).fetchall()


class SharedConnectionTest(Fixture):
    def test_the_database_is_in_wal_mode_after_the_first_connect(self):
        connect(self.db).close()
        self.assertEqual(sqlite3.connect(self.db).execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_a_writer_holding_a_transaction_does_not_fail_another_writer_within_the_timeout(self):
        connect(self.db).close()
        holder = open_db(self.db)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO sessions (session_id) VALUES ('held')")
        errors = []

        def write():
            try:
                other = open_db(self.db)
                other.execute("INSERT INTO sessions (session_id) VALUES ('waited')")  # waits, no "database is locked"
                other.commit()
            except sqlite3.OperationalError as e:
                errors.append(e)

        t = threading.Thread(target=write)
        t.start()
        time.sleep(0.5)
        holder.commit()
        t.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(r[0] for r in holder.execute("SELECT session_id FROM sessions")), ["held", "waited"])

    def test_no_module_opens_the_database_file_without_the_shared_settings(self):
        root = Path(__file__).resolve().parent.parent / "tokscope"
        raw = [str(p.relative_to(root)) for p in root.rglob("*.py") if "sqlite3.connect(" in p.read_text() and p.name != "ingest.py"]
        self.assertEqual(raw, ["core/privacy.py"])  # only privacy's ":memory:" copy


class IngestTest(Fixture):
    def test_a_resumed_session_repeating_earlier_requests_in_its_file_counts_them_once(self):
        # issue #46: resume appends to the same file, so replayed lines share the session and key
        self.write_main([human("hi"), assistant("r1", out=40), human("again"), assistant("r2"), assistant("r1", out=40)])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT count(*), sum(output) FROM requests"), [(2, 50)])

    def test_a_fork_copying_earlier_requests_into_a_new_file_does_not_count_them_twice(self):
        # issue #46, confirmed with `claude -p --resume <id> --fork-session`: the fork repeats requests and their keys
        def write(name, records):
            (self.project / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

        base = [human("hi"), assistant("r1", out=40), human("again"), assistant("r2")]
        write("a-orig", base)
        # the original is resumed after the fork, so its last_ts is the later one
        write("b-fork", base + [human("more", ts="2026-10-01T00:05:00Z"), assistant("r3")])
        write("a-orig", base + [human("later", ts="2026-10-01T00:09:00Z")])
        for order in ("a-orig", "b-fork"):  # the same result whichever file is parsed first
            self.db.unlink(missing_ok=True)
            self.run_ingest()
            self.assertEqual(self.rows("SELECT session_id, request_key FROM requests ORDER BY request_key"),
                             [("a-orig", "r1"), ("a-orig", "r2"), ("b-fork", "r3")])
            (self.project / f"{order}.jsonl").touch()
            self.run_ingest()
            self.assertEqual(self.rows("SELECT count(*), sum(output) FROM requests"), [(3, 60)])

    def test_streamed_lines_of_one_request_count_once(self):
        # Claude Code writes one line per content block, each repeating the request's usage
        self.write_main([human("hi"), assistant("r1", out=5), assistant("r1", out=40), assistant("r1", out=40)])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT count(*), sum(output) FROM requests"), [(1, 40)])

    def test_skill_owns_later_requests_until_next_human_prompt_but_phase_carries(self):
        self.write_main([
            human("plan it"),
            assistant("r1", tools=[("t1", "Skill", {"skill": "writing-plans"})]),
            assistant("r2"),
            notification("<task-notification>done</task-notification>"),
            assistant("r3"),
            human("ok continue"),
            assistant("r4"),
        ])
        self.run_ingest()
        got = self.rows("SELECT request_key, skill, phase, prompt_idx FROM requests ORDER BY request_key")
        self.assertEqual(got, [
            ("r1", None, None, 1),  # the request that calls Skill ran before the skill loaded
            ("r2", "writing-plans", "plan", 1),
            ("r3", "writing-plans", "plan", 1),  # a background notification is not a new human prompt
            ("r4", None, "plan", 2),
        ])

    def test_a_load_keeps_the_hash_of_the_skill_text_its_request_blob_carried(self):
        text = "Base directory for this skill: /x/review\n\n# Review\nRead the diff.\n\n\nARGUMENTS: the PR"
        blob = {"type": "api-request-blob", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "Launching skill: review"}, {"type": "text", "text": text}]}}
        self.write_main([human("review it"), assistant("r1", tools=[("t1", "Skill", {"skill": "review"})]), blob, assistant("r2")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT skill, tool_use_id, text_hash FROM skill_calls"), [("review", "t1", loaded_text_hash(text))])
        self.assertEqual(loaded_text_hash(text), loaded_text_hash(text.replace("the PR", "another PR")))  # arguments differ, text same

    def test_arguments_put_inside_the_skill_text_do_not_change_its_hash(self):
        inline = "Base directory for this skill: /x\n\n# Research\n`{}` is the feature to research.\n"
        placeholder = loaded_text_hash(inline.format("$ARGUMENTS"))
        for args in ("ENG-1 creds", "ddtrace 2 to 4"):
            self.assertIn(placeholder, loaded_text_hash(inline.format(args), args).split())

    def test_a_short_argument_that_is_also_a_word_of_the_skill_still_matches_the_plain_text(self):
        text = "Base directory for this skill: /x\n\n# Wiki\nRun update when the source changed.\n\n\nARGUMENTS: update"
        plain = loaded_text_hash("Base directory for this skill: /x\n\n# Wiki\nRun update when the source changed.")
        self.assertIn(plain, loaded_text_hash(text, "update").split())

    def test_a_typed_skill_command_keeps_the_hash_of_the_text_its_meta_message_carried(self):
        cmd = "<command-message>review</command-message>\n<command-name>/review</command-name>\n<command-args>PR 12</command-args>"
        text = "Base directory for this skill: /x/review\n\n# Review\nReview $ARGUMENTS.".replace("$ARGUMENTS", "PR 12")
        meta = {"type": "user", "isMeta": True, "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.write_main([human(cmd), meta, assistant("r1")])
        self.run_ingest()
        (skill, source, text_hash), = self.rows("SELECT skill, source, text_hash FROM skill_calls")
        self.assertEqual((skill, source), ("review", "command"))
        self.assertIn(loaded_text_hash("Base directory for this skill: /x\n\n# Review\nReview $ARGUMENTS."), text_hash.split())

    def test_a_plugin_skill_called_by_its_bare_name_is_stored_under_its_full_name(self):
        install = self.tmp / "home" / "cache" / "ce"
        (install / "skills" / "simplify").mkdir(parents=True)
        (install / "skills" / "simplify" / "SKILL.md").write_text("# s")
        plugins = self.tmp / "home" / ".claude" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {"ce@m": [{"scope": "user", "installPath": str(install)}]}}))
        self.write_main([human("go"), assistant("r1", tools=[("t1", "Skill", {"skill": "simplify"})]), assistant("r2"),
                         human("again"), assistant("r3", tools=[("t2", "Skill", {"skill": "ce:simplify"})]), assistant("r4")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT DISTINCT skill FROM skill_calls"), [("ce:simplify",)])
        self.assertEqual(self.rows("SELECT DISTINCT skill FROM requests WHERE skill IS NOT NULL"), [("ce:simplify",)])

    def test_typed_skill_command_loads_skill_and_builtin_command_is_not_a_prompt(self):
        self.write_main([
            human("<command-name>/model</command-name>"),
            human("<command-message>feature-intake</command-message>\n<command-name>/feature-intake</command-name>"),
            assistant("r1"),
        ])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT skill, phase, prompt_idx FROM requests"), [("feature-intake", "intake", 1)])
        self.assertEqual(self.rows("SELECT prompts FROM sessions"), [(1,)])
        self.assertEqual(self.rows("SELECT skill, source FROM skill_calls"), [("feature-intake", "command")])

    def test_subagent_inherits_context_of_spawning_call_and_nested_agent_its_parent(self):
        self.write_main([
            human("review"),
            assistant("r1", tools=[("t1", "Skill", {"skill": "correctness-review"})]),
            assistant("r2", tools=[("t2", "Agent", {"subagent_type": "reviewer"})]),
        ])
        self.write_agent("a1", {"agentType": "reviewer", "toolUseId": "t2", "spawnDepth": 1},
                         [assistant("r3", tools=[("t3", "Agent", {})])])
        self.write_agent("a2", {"agentType": "correctness-scorer", "toolUseId": "t3", "spawnDepth": 2},
                         [assistant("r4")])
        self.run_ingest()
        got = self.rows("SELECT request_key, agent_type, skill, phase FROM requests ORDER BY request_key")
        self.assertEqual(got[2:], [
            ("r3", "reviewer", "correctness-review", "review"),
            ("r4", "correctness-scorer", "correctness-review", "review"),
        ])
        self.assertEqual(self.rows("SELECT agent_id, parent_agent_id FROM subagents ORDER BY agent_id"),
                         [("a1", None), ("a2", "a1")])

    def test_prompt_text_is_kept_short_and_commands_show_their_name(self):
        self.write_main([
            human("<command-message>uat</command-message>\n<command-name>/uat</command-name>\n<command-args>run it</command-args>"),
            assistant("r1"),
            human("fix   the\nbug " + "x" * 300),
            assistant("r2"),
        ])
        self.run_ingest()
        rows = self.rows("SELECT prompt_idx, text FROM prompts ORDER BY prompt_idx")
        self.assertEqual(rows[0], (1, "/uat run it"))
        self.assertTrue(rows[1][1].startswith("fix the bug x"))
        self.assertEqual(len(rows[1][1]), 160)

    def test_an_interrupt_marker_is_not_a_prompt(self):
        self.write_main([human("go"), assistant("r1"), human("[Request interrupted by user]"), human("again"), assistant("r2")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT prompts FROM sessions"), [(2,)])
        self.assertEqual(self.rows("SELECT text FROM prompts ORDER BY prompt_idx"), [("go",), ("again",)])

    def test_synthetic_messages_are_not_billed(self):
        self.write_main([human("x"), assistant("r1", model="<synthetic>")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT count(*) FROM requests"), [(0,)])

    def test_one_hour_cache_write_costs_twice_input_rate(self):
        # matches OTel cost_usd for the 2026-10-20 haiku probe: 2 in, 59128 1h-write, 367 out
        self.assertAlmostEqual(cost_usd("claude-haiku-5-5", 2, 367, 0, 0, 59128), 0.0120093, places=7)
        self.assertGreater(cost_usd("claude-opus-5-5", 0, 0, 0, 0, 1000), cost_usd("claude-opus-5-5", 0, 0, 0, 1000, 0))

    def test_sonnet_5_5_cache_read_matches_claude_code_cost(self):
        # 2026-10-20 bench run 7949b34d, first request: OTel cost_usd 0.0059908
        self.assertAlmostEqual(cost_usd("claude-sonnet-5-5", 2, 236, 36268, 0, 0), 0.0059908, places=7)

    def test_unknown_model_has_null_cost_not_zero(self):
        self.write_main([human("x"), assistant("r1", model="claude-future-9")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT cost_usd FROM requests"), [(None,)])

    def test_reingest_skips_unchanged_and_replaces_changed_without_duplicates(self):
        self.write_main([human("x"), assistant("r1")])
        self.assertEqual(self.run_ingest(), (1, 0))
        self.assertEqual(self.run_ingest(), (0, 1))
        self.write_main([human("x"), assistant("r1"), assistant("r2", out=99)])
        self.assertEqual(self.run_ingest(), (1, 0))
        self.assertEqual(self.rows("SELECT count(*) FROM requests"), [(2,)])


class IncrementalTest(Fixture):
    BASE = [
        human("plan it"), assistant("r1", tools=[("t1", "Skill", {"skill": "writing-plans"})]), assistant("r2", out=5),
        assistant("r2", out=9, tools=[("t2", "Agent", {})]), result("t2", "ok"),
    ]
    MORE = [human("go on", ts="2026-10-01T00:05:00Z"), assistant("r3", tools=[("t3", "Bash", {"command": "ls"})]),
            result("t3", "files"), assistant("r2", out=20)]

    def write_agent_lines(self, records):
        self.write_agent("a1", {"agentType": "Explore", "toolUseId": "t2", "spawnDepth": 1}, records)

    def append(self, path, records):
        with open(path, "a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in records))

    def dump(self, db):
        conn = sqlite3.connect(db)
        out = {}
        for t in ("sessions", "requests", "subagents", "skill_calls", "prompts", "tool_calls", "headless_calls"):
            out[t] = sorted(map(repr, conn.execute(f"SELECT * FROM {t}")))
        return out

    def parsed_lines(self):
        """Lines the next ingest reads from the transcripts."""
        parsers = []
        real = ingest_mod.parse_session
        with mock.patch.object(ingest_mod, "parse_session", side_effect=lambda *a: parsers.append(real(*a)) or parsers[-1]):
            self.run_ingest()
        return sum(p.lines_read for p in parsers)

    def test_appended_lines_are_the_only_ones_read_and_the_result_equals_a_full_parse(self):
        main = self.project / f"{SID}.jsonl"
        self.write_main(self.BASE)
        self.write_agent_lines([assistant("r4")])
        self.run_ingest()
        self.append(main, self.MORE)
        self.append(self.project / SID / "subagents" / "agent-a1.jsonl", [assistant("r5", out=7)])
        self.assertEqual(self.parsed_lines(), len(self.MORE) + 1)
        got = self.dump(self.db)
        self.db.unlink()
        for ext in ("-wal", "-shm"):
            Path(str(self.db) + ext).unlink(missing_ok=True)
        self.run_ingest()
        self.assertEqual(got, self.dump(self.db))

    def test_a_new_subagent_file_and_an_unchanged_session_resume_to_the_full_result(self):
        main = self.project / f"{SID}.jsonl"
        self.write_main(self.BASE)
        self.run_ingest()
        self.append(main, self.MORE)
        self.write_agent_lines([assistant("r4")])
        self.run_ingest()
        got = self.dump(self.db)
        self.db.unlink()
        self.run_ingest()
        self.assertEqual(got, self.dump(self.db))

    def test_a_request_shared_with_an_earlier_session_stays_with_it_when_the_later_one_grows(self):
        base = [human("hi"), assistant("r1", out=40)]
        (self.project / "a-orig.jsonl").write_text("".join(json.dumps(r) + "\n" for r in base))
        fork = self.project / "b-fork.jsonl"
        fork.write_text("".join(json.dumps(r) + "\n" for r in [*base, human("more", ts="2026-10-01T00:05:00Z")]))
        self.run_ingest()
        self.append(fork, [assistant("r3")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT session_id, request_key FROM requests ORDER BY request_key"),
                         [("a-orig", "r1"), ("b-fork", "r3")])

    def test_a_truncated_or_rewritten_file_is_parsed_in_full(self):
        main = self.project / f"{SID}.jsonl"
        self.write_main(self.BASE + self.MORE)
        self.run_ingest()
        self.write_main(self.BASE[:3])  # shorter than the stored offset
        self.assertEqual(self.parsed_lines(), 3)
        self.assertEqual(self.rows("SELECT count(*) FROM requests"), [(2,)])
        self.write_main([human("other")] + self.BASE[1:] + self.MORE)  # longer, but the bytes before the offset differ
        self.assertEqual(self.parsed_lines(), 1 + len(self.BASE) - 1 + len(self.MORE))
        self.assertEqual(self.rows("SELECT count(*) FROM requests WHERE request_key = 'r3'"), [(1,)])

    def test_a_half_written_last_line_waits_for_its_end(self):
        main = self.project / f"{SID}.jsonl"
        self.write_main(self.BASE)
        line = json.dumps(assistant("r9"))
        with open(main, "a") as f:
            f.write(line[:30])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT count(*) FROM requests WHERE request_key = 'r9'"), [(0,)])
        with open(main, "a") as f:
            f.write(line[30:] + "\n")
        self.run_ingest()
        self.assertEqual(self.rows("SELECT count(*) FROM requests WHERE request_key = 'r9'"), [(1,)])


class ConfigDirTest(Fixture):
    def test_claude_config_dir_is_read(self):
        (self.tmp / "cfg").mkdir()
        self.project.parent.rename(self.tmp / "cfg" / "projects")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "cfg")}):
            self.write_main_at(self.tmp / "cfg" / "projects" / "proj")
            self.assertEqual(ingest(self.db, PHASES, log=lambda *_: None), (1, 0))

    def write_main_at(self, d):
        (d / f"{SID}.jsonl").write_text(json.dumps(human("hi")) + "\n" + json.dumps(assistant("r1")) + "\n")

    def test_sessions_from_two_dirs_are_ingested_once_each(self):
        other = self.tmp / "other" / "proj"
        other.mkdir(parents=True)
        self.write_main_at(self.project)
        self.write_main_at(other)  # the same session id in both: counted once
        (other / "s2.jsonl").write_text(json.dumps(human("hi")) + "\n" + json.dumps(assistant("r9")) + "\n")
        dirs = [self.tmp / "projects", self.tmp / "other", self.tmp / "projects"]
        self.assertEqual(ingest(self.db, PHASES, projects_dir=dirs, log=lambda *_: None), (2, 0))
        self.assertEqual(self.rows("SELECT count(*) FROM sessions"), [(2,)])
        self.assertEqual(self.rows("SELECT count(*) FROM requests"), [(2,)])


class MissingDirTest(Fixture):
    def test_missing_projects_dir(self):
        logs = []
        self.assertEqual(ingest(self.db, PHASES, projects_dir=self.tmp / "nope", log=logs.append), (0, 0))
        self.assertEqual(len(logs), 1)
        self.assertIn("no transcripts", logs[0])


class SessionCommandTest(Fixture):
    def test_session_breakdown_is_read_fresh_from_the_transcript(self):
        from tokscope.cli import session_text
        from tokscope.core.ingest import ingest_session

        self.write_main([human("x"), assistant("r1", tools=[("t1", "Skill", {"skill": "uat"})]), assistant("r2")])
        self.assertTrue(ingest_session(self.db, PHASES, SID, projects_dir=self.tmp / "projects"))
        text = session_text(sqlite3.connect(self.db), SID)
        self.assertIn("2 requests", text)
        self.assertIn("uat", text)
        self.assertIn("verify", text)
        self.assertFalse(ingest_session(self.db, PHASES, "missing", projects_dir=self.tmp / "projects"))

    def test_session_json_splits_main_and_subagents_and_names_the_last_prompt(self):
        from tokscope.cli import session_json
        from tokscope.core.ingest import ingest_session

        self.write_main([human("first"), assistant("r1"), human("second ask"),
                         assistant("r2", tools=[("t1", "Agent", {"subagent_type": "Explore"})])])
        self.write_agent("a1", {"agentType": "Explore", "toolUseId": "t1", "spawnDepth": 1}, [assistant("r3")])
        ingest_session(self.db, PHASES, SID, projects_dir=self.tmp / "projects")
        j = session_json(sqlite3.connect(self.db), SID)
        self.assertEqual((j["runs"], j["prompts"]), (1, 2))
        self.assertEqual(j["main"] + j["agents"], j["tokens"])
        self.assertGreater(j["agents"], 0)
        self.assertEqual((j["last"]["i"], j["last"]["text"]), (2, "second ask"))
        self.assertTrue(session_json(sqlite3.connect(self.db), "missing")["empty"])

    def test_session_turns_show_in_out_price_and_which_agents_mcp_and_tools_ran(self):
        from tokscope.cli import session_json
        from tokscope.core.ingest import ingest_session

        self.write_main([
            human("plain question"), assistant("r1"),
            human("dig in"),
            assistant("r2", tools=[("t1", "Bash", {}), ("t2", "mcp__plugin_datadog_mcp__search_datadog_logs", {}),
                                   ("t3", "Agent", {"subagent_type": "Explore"})]),
            result("t1", "ok" * 4), result("t2", "x" * 800),
            assistant("r3", tools=[("t4", "Bash", {}), ("t5", "mcp__claude_ai_Linear__get_issue", {})]),
            human("odd model"), assistant("r5", model="claude-unknown-9"),
        ])
        self.write_agent("a1", {"agentType": "Explore", "toolUseId": "t3", "spawnDepth": 1, "description": "find the logs"},
                         [assistant("r4", tools=[("t6", "mcp__plugin_datadog_mcp__get_datadog_trace", {})]),
                          result("t6", [{"type": "text", "text": "y" * 400}])])
        ingest_session(self.db, PHASES, SID, projects_dir=self.tmp / "projects")
        odd, dig, plain = session_json(sqlite3.connect(self.db), SID)["turns"]
        self.assertEqual((plain["agents"], plain["mcp"], plain["tools"]), ([], [], []))
        self.assertEqual((plain["in"], plain["out"]), (101, 10))
        self.assertAlmostEqual(plain["usd"], cost_usd("claude-opus-5-5", 1, 10, 100, 0, 0))
        # tool calls made inside the subagent count for the prompt that spawned it
        self.assertEqual(dig["agents"], [["Explore", 1, 1 + 100 + 10]])
        self.assertEqual([(r["type"], r["desc"], r["depth"], r["tokens"]) for r in dig["runs"]],
                         [("Explore", "find the logs", 1, 1 + 100 + 10)])
        self.assertEqual(plain["runs"], [])
        self.assertEqual(dig["mcp"], [["datadog", 2, 300], ["Linear", 1, 0]])
        self.assertEqual(dig["tools"], [["Bash", 2, 2]])
        self.assertEqual(dig["requests"], 3)
        self.assertEqual(dig["out"], 30)
        self.assertIsNone(odd["usd"])

    def test_marks_append_with_a_receive_time_and_skip_blank_lines(self):
        from tokscope.cli import append_marks

        marks = self.tmp / "marks"
        self.assertEqual(append_marks(['{"skill": "uat"}\n', "\n"], marks), 1)
        self.assertEqual(append_marks(['{"skill": "xia2"}\n'], marks), 1)
        lines = [json.loads(line) for f in marks.iterdir() for line in f.read_text().splitlines()]
        self.assertEqual([m["skill"] for m in lines], ["uat", "xia2"])
        self.assertTrue(all("received_at" in m for m in lines))



PARENT, CHILD, GRANDCHILD = (f"{n}0000000-0000-4000-8000-000000000000" for n in "abc")


def at(rec, ts, cwd="/repo", entrypoint="cli"):
    return {**rec, "timestamp": ts, "cwd": cwd, "entrypoint": entrypoint}


def bash(req, tid, command, ts, cwd="/repo", **inp):
    return at(assistant(req, tools=[(tid, "Bash", {"command": command, **inp})]), ts, cwd)


def headless(ts, cwd="/repo", req="h1"):
    """The start of a `claude -p` session: its prompt comes from the SDK."""
    return [at({**human("do the thing"), "turnOrigin": "sdk"}, ts, cwd, "sdk-cli"),
            at(assistant(req), ts, cwd, "sdk-cli")]


class HeadlessLinkTest(Fixture):
    def write(self, sid, records):
        (self.project / f"{sid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    def parents(self):
        return dict(self.rows("SELECT session_id, parent_session_id FROM sessions"))

    def test_child_links_by_the_session_id_its_parents_bash_result_printed(self):
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "claude -p 'hi' --output-format json", "2026-10-01T00:00:01Z"),
                            at(result("t1", f'{{"session_id": "{CHILD}"}}'), "2026-10-01T00:05:00Z")])
        # another cwd, and it starts after the call returned: only the printed id links it
        self.write(CHILD, headless("2026-10-01T00:06:00Z", cwd="/elsewhere"))
        self.run_ingest()
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT})
        self.assertEqual(self.rows(f"SELECT entrypoint FROM sessions WHERE session_id = '{CHILD}'"), [("sdk-cli",)])

    def test_child_links_by_starting_in_the_same_cwd_while_the_call_ran(self):
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "cd /repo && timeout 90 claude --model haiku -p 'hi'", "2026-10-01T00:00:01Z"),
                            at(result("t1", "done"), "2026-10-01T00:05:00Z")])
        self.write(CHILD, headless("2026-10-01T00:00:03Z"))
        # outside the window, in another cwd, or not headless: no parent
        self.write("late", headless("2026-10-01T00:06:00Z", req="h2"))
        self.write("other-cwd", headless("2026-10-01T00:00:04Z", cwd="/other", req="h3"))
        self.write("typed", [at(human("hi"), "2026-10-01T00:00:05Z"), at(assistant("h4"), "2026-10-01T00:00:05Z")])
        self.run_ingest()
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT, "late": None, "other-cwd": None, "typed": None})

    def test_a_call_that_printed_its_childs_id_adopts_no_other_run_by_window(self):
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "claude -p 'hi' --output-format json", "2026-10-01T00:00:01Z"),
                            at(result("t1", f'{{"session_id": "{CHILD}"}}'), "2026-10-01T00:05:00Z")])
        self.write(CHILD, headless("2026-10-01T00:00:02Z"))
        # a web app's run in the same folder while the call ran: the call already named its child
        self.write("web", headless("2026-10-01T00:02:00Z", req="h2"))
        self.run_ingest()
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT, "web": None})

    def test_a_path_inside_the_prompt_is_not_a_folder_the_call_runs_in(self):
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "claude -p \"review /home/u/projX please\" <<'EOF'\nsee /home/u/projY\nEOF",
                                 "2026-10-01T00:00:01Z"),
                            at(result("t1", "done"), "2026-10-01T00:05:00Z")])
        self.write("in-x", headless("2026-10-01T00:00:02Z", cwd="/home/u/projX", req="h2"))
        self.write("in-y", headless("2026-10-01T00:00:03Z", cwd="/home/u/projY", req="h3"))
        self.write(CHILD, headless("2026-10-01T00:00:04Z", req="h4"))  # the call's own cwd still links
        self.run_ingest()
        self.assertEqual(self.parents(), {PARENT: None, "in-x": None, "in-y": None, CHILD: PARENT})

    def test_a_heredoc_script_keeps_its_folder_and_a_listed_id_keeps_the_window(self):
        script = "cat > /tmp/run.sh <<'EOF'\ncd /work/proj && claude -p hi\nEOF\nbash /tmp/run.sh"
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", script, "2026-10-01T00:00:01Z"),
                            at(result("t1", "done"), "2026-10-01T00:05:00Z"),
                            # this call only lists an older session's id: it keeps its window
                            bash("r2", "t2", "ls ~/.claude/projects/x; claude -p again", "2026-10-01T00:10:00Z"),
                            at(result("t2", f"{CHILD}.jsonl"), "2026-10-01T00:15:00Z")])
        self.write(CHILD, headless("2026-10-01T00:00:03Z", cwd="/work/proj"))
        self.write(GRANDCHILD, headless("2026-10-01T00:11:00Z", req="h2"))
        self.run_ingest()
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT, GRANDCHILD: PARENT})

    def test_command_dirs_reads_shell_words_not_prompt_text(self):
        from tokscope.core.ingest import command_dirs
        cases = {
            'cd "/x" && claude -p hi': {"/x"},
            "cd '/a b/c' && claude -p hi": {"/a b/c"},
            'X="/p q"; cd "$X" && claude -p hi': {"/p q"},
            "cd $'/x' && claude -p hi": {"/x"},
            "cd `echo /x` && claude -p hi": {"/x"},
            'claude -p "review /home/u/projX please"': set(),
            "claude -p hi <<'EOF'\nsee /home/u/projY\nEOF": set(),
            "cat > r.sh <<'EOF'\ncd /x/proj && claude -p hi\nEOF\nbash r.sh": {"/x/proj"},
            "cat > r.sh <<'EOF'\ncd /x/proj && claude -p hi\nEOF\nclaude -p yo": set(),
        }
        for command, dirs in cases.items():
            with self.subTest(command=command):
                self.assertEqual(set(command_dirs(command, "/c").split("\n")) - {"/c"}, dirs)

    def test_a_background_call_ends_at_its_task_notification_and_nested_runs_link_each_level(self):
        done = notification("<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>t1</tool-use-id>\n"
                            "<status>completed</status>\n</task-notification>")
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "claude -p 'hi'", "2026-10-01T00:00:01Z", run_in_background=True),
                            at(result("t1", "Command running in background with ID: b1"), "2026-10-01T00:00:02Z"),
                            at(done, "2026-10-01T00:20:00Z"),
                            at(human("later"), "2026-10-01T08:00:00Z")])
        self.write(CHILD, [*headless("2026-10-01T00:10:00Z"),
                           bash("r9", "t9", "claude -p 'deeper'", "2026-10-01T00:10:05Z"),
                           at(result("t9", "ok"), "2026-10-01T00:12:00Z")])
        self.write(GRANDCHILD, headless("2026-10-01T00:10:06Z", req="h2"))
        # after the notification, while the parent session is still open: not its child
        self.write("after-done", headless("2026-10-01T03:00:00Z", req="h3"))
        self.run_ingest()
        # the grandchild started inside both calls: the latest one is its parent
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT, GRANDCHILD: CHILD, "after-done": None})

    def test_a_background_call_with_no_notification_links_no_window_child(self):
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "claude -p 'hi'", "2026-10-01T00:00:01Z", run_in_background=True),
                            at(result("t1", "Command running in background with ID: b1"), "2026-10-01T00:00:02Z"),
                            at(human("later"), "2026-10-01T08:00:00Z")])
        self.write(CHILD, headless("2026-10-01T02:00:00Z"))
        self.run_ingest()
        self.assertEqual(self.parents(), {PARENT: None, CHILD: None})

    def test_child_links_in_a_folder_the_command_names_or_the_parents_scratchpad(self):
        pad = f"/tmp/claude-1000/-repo/{PARENT}/scratchpad/probe"
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "SP=/work/e2e; cd \"$SP/repo\" && claude -p hi", "2026-10-01T00:00:01Z"),
                            at(result("t1", "ok"), "2026-10-01T00:05:00Z"),
                            bash("r2", "t2", "cd $(mktemp -d) && claude -p hi", "2026-10-01T00:10:00Z"),
                            at(result("t2", "ok"), "2026-10-01T00:15:00Z")])
        self.write(CHILD, headless("2026-10-01T00:00:03Z", cwd="/work/e2e/repo"))
        self.write(GRANDCHILD, headless("2026-10-01T00:10:03Z", cwd=pad, req="h2"))
        self.write("stranger", headless("2026-10-01T00:10:04Z", cwd="/tmp/x", req="h3"))
        self.run_ingest()
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT, GRANDCHILD: PARENT, "stranger": None})

    def test_commands_that_only_mention_claude_are_not_headless_runs(self):
        from tokscope.core.ingest import HEADLESS_RE

        for cmd in ("claude -p hi", "npx claude --print 'x'", "/usr/bin/claude -p x", "(claude -p x)", "a; claude --model m -p x"):
            self.assertTrue(HEADLESS_RE.search(cmd), cmd)
        for cmd in ("ls ~/.claude -p", "cd claude-code-tokscope && ls -p", "claude --resume x", "grep claude -r . | head -p"):
            self.assertFalse(HEADLESS_RE.search(cmd), cmd)
        # quoted words and heredoc bodies are text the command passes along, not a run
        from tokscope.core.ingest import is_headless
        self.assertTrue(is_headless("cd /x && claude -p \"do it\" --output-format json"))
        # a script written by a heredoc and run in the same command
        self.assertTrue(is_headless("cat > $S/run.sh <<'EOF'\ncd /x && claude -p hi\nEOF\nbash $S/run.sh $S"))
        self.assertFalse(is_headless("cat > $S/run.sh <<'EOF'\nclaude -p hi\nEOF\necho saved"))
        for cmd in ('git commit -m "Run claude -p in CI"', "gh pr create --body 'A (`claude -p`) run'",
                    "git commit -F - <<'EOF'\nshow claude -p runs\nEOF\ngit push"):
            self.assertFalse(is_headless(cmd), cmd)

    def test_session_list_names_the_parent_and_an_old_database_gains_the_columns(self):
        from tokscope.core.ingest import connect
        from tokscope.web.report.sections.sessions import _sessions_json

        old = sqlite3.connect(self.db)
        old.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, project TEXT, cwd TEXT, title TEXT, version TEXT,"
                    " first_ts TEXT, last_ts TEXT, prompts INTEGER, signature TEXT)")
        old.commit()
        old.close()
        connect(self.db).close()
        self.assertIn("parent_session_id", {c[1] for c in self.rows("PRAGMA table_info(sessions)")})
        self.write(PARENT, [at(human("ship the release"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "claude -p hi", "2026-10-01T00:00:01Z"),
                            at(result("t1", "ok"), "2026-10-01T00:05:00Z")])
        self.write(CHILD, headless("2026-10-01T00:00:03Z"))
        self.run_ingest()
        rows = {s["id"]: s for s in _sessions_json(sqlite3.connect(self.db), "WHERE 1", ())}
        self.assertEqual((rows[CHILD]["parent"], rows[CHILD]["parent_title"]), (PARENT, "“ship the release”"))
        self.assertNotIn("parent", rows[PARENT])


    def test_a_parent_outside_the_reports_filter_keeps_its_id_but_not_its_title(self):
        from tokscope.web.report.sections.sessions import _sessions_json

        other = self.tmp / "projects" / "other"  # the parent lives in another project
        other.mkdir()
        (other / f"{PARENT}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            at(human("ship the secret release"), "2026-10-01T00:00:00Z"),
            bash("r1", "t1", "claude -p hi", "2026-10-01T00:00:01Z"),
            at(result("t1", "ok"), "2026-10-01T00:05:00Z")]))
        self.write(CHILD, headless("2026-10-01T00:00:03Z"))
        self.run_ingest()
        self.assertEqual(self.parents()[CHILD], PARENT)
        rows = {s["id"]: s for s in _sessions_json(sqlite3.connect(self.db), "WHERE s.project = ?", ("proj",))}
        self.assertEqual(set(rows), {CHILD})
        self.assertEqual((rows[CHILD]["parent"], rows[CHILD]["parent_title"]), (PARENT, f"session {PARENT[:8]}"))
        self.assertNotIn("secret", str(rows))

    def test_links_are_repaired_on_the_next_run_and_are_not_rewritten_when_right(self):
        self.write(PARENT, [at(human("go"), "2026-10-01T00:00:00Z"),
                            bash("r1", "t1", "claude -p hi", "2026-10-01T00:00:01Z"),
                            at(result("t1", "ok"), "2026-10-01T00:05:00Z")])
        self.write(CHILD, headless("2026-10-01T00:00:03Z"))
        self.run_ingest()
        # a run that stored the sessions but stopped before linking: the next run, with nothing to parse, links them
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE sessions SET parent_session_id = NULL")
        self.assertEqual(self.run_ingest()[0], 0)
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT})
        from tokscope.core.ingest import connect, link_sessions

        conn = connect(self.db)
        before = conn.total_changes
        link_sessions(conn)  # the links are already right: no row is written
        self.assertEqual(conn.total_changes, before)
        self.assertEqual(self.parents(), {PARENT: None, CHILD: PARENT})

if __name__ == "__main__":
    unittest.main()
