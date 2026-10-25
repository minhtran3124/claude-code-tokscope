import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope.core import skills
from tokscope.cli import record_skill_versions
from tokscope.core.ingest import connect
from tokscope.web.report import write_report


def write_skill(folder, body="# rules\n", extra=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(body)
    for name, text in (extra or {}).items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    return folder


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "TOKSCOPE_HOME": str(self.tmp / "data-home")})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.tmp / "repo"
        self.skill = write_skill(self.repo / ".claude" / "skills" / "review", "---\nname: review\nversion: 1.2.0\n---\n# v1\n")
        skills.canonical_name.cache_clear()
        self.conn = connect(self.tmp / "t.db")
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd) VALUES ('s1', 'p', ?)", (str(self.repo / "src"),))

    def load(self, ts, prompt, tool_use_id=None, tokens=100, text_hash=None):
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, phase, source, prompt_idx, tool_use_id, text_hash) "
                          "VALUES ('s1', ?, 'review', 'review', 'tool', ?, ?, ?)", (ts, prompt, tool_use_id, text_hash))
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, skill, phase, input, output, "
                          "cache_read, cache_write_5m, cache_write_1h, cost_usd) VALUES ('s1', ?, ?, 'm', ?, 'review', 'review', "
                          "?, 0, 0, 0, 0, 0)", (f"r{prompt}", ts, prompt, tokens))

    def test_partial_snapshot_is_repaired_on_next_record(self):
        write_skill(self.skill, "# v1\n", {"ref/a.md": "A", "ref/b.md": "B"})
        v = skills.record(self.conn, "review", self.skill, "2026-01-01T00:00:00+00:00", "scan")
        dest = self.tmp / "data-home" / "data" / "skills" / "review" / v
        self.assertEqual(skills.fingerprint(dest), v)
        (dest / "ref" / "b.md").unlink()  # a crash left a short copy
        self.assertNotEqual(skills.fingerprint(dest), v)
        skills.record(self.conn, "review", self.skill, "2026-01-02T00:00:00+00:00", "scan")
        self.assertEqual(skills.fingerprint(dest), v)
        self.assertFalse(list(dest.parent.glob(".*.tmp")))

    def test_ordinary_skill_keeps_its_hash(self):
        self.assertEqual(skills.body_hash(self.skill), "b9f04a790a4a")  # pinned: a parser change must not move it

    def test_frontmatter_is_delimited_by_lines_of_exactly_three_dashes(self):
        both = write_skill(self.tmp / "dash", "---\nname: d\nversion: 2.0\ndescription: a --- b\n---\nBODY\n")
        self.assertEqual(skills._body((both / "SKILL.md").read_text()), "BODY")
        self.assertEqual(skills.label(both), "2.0")
        rule = "---\nNot frontmatter\n"
        self.assertEqual(skills._body(rule), rule.strip())
        self.assertIsNone(skills.label(write_skill(self.tmp / "rule", rule)))
        self.assertEqual(skills._body("---\nname: x\n---\n---\nrule\n"), "---\nrule")

    def test_crlf_frontmatter(self):
        crlf = write_skill(self.tmp / "crlf", "---\r\nname: c\r\nversion: 3.1\r\n---\r\nBODY\r\n")
        self.assertEqual(skills._body((crlf / "SKILL.md").read_bytes().decode()), "BODY")
        self.assertEqual(skills.label(crlf), "3.1")

    def test_the_fingerprint_is_the_content_not_the_place_or_the_clock(self):
        twin = write_skill(self.tmp / "elsewhere" / "review", (self.skill / "SKILL.md").read_text())
        self.assertEqual(skills.fingerprint(self.skill), skills.fingerprint(twin))
        (twin / ".DS_Store").write_text("x")
        (twin / "__pycache__").mkdir()
        (twin / "__pycache__" / "a.pyc").write_text("x")
        os.utime(twin / "SKILL.md", (0, 0))
        self.assertEqual(skills.fingerprint(self.skill), skills.fingerprint(twin))
        (twin / "references.md").write_text("new rule")
        self.assertNotEqual(skills.fingerprint(self.skill), skills.fingerprint(twin))
        self.assertIsNone(skills.fingerprint(self.tmp / "nothing"))

    def test_eval_output_and_big_files_in_the_folder_are_not_a_new_version(self):
        before = skills.fingerprint(self.skill)
        (self.skill / "eval" / "results").mkdir(parents=True)
        (self.skill / "eval" / "results" / "run1.json").write_text("{}")
        (self.skill / "dataset.jsonl").write_bytes(b"x" * (skills.MAX_BYTES + 1))
        self.assertEqual(skills.fingerprint(self.skill), before)

    def test_only_top_level_bench_folders_are_ignored_and_crlf_is_the_same_as_lf(self):
        before = skills.fingerprint(self.skill)
        (self.skill / "assets" / "results").mkdir(parents=True)
        (self.skill / "assets" / "results" / "r.md").write_text("kept")
        self.assertNotEqual(skills.fingerprint(self.skill), before)
        (self.skill / "tests").mkdir()
        (self.skill / "tests" / "t.md").write_text("ignored")
        lf = write_skill(self.tmp / "lf" / "review", "a\nb\n")
        crlf = write_skill(self.tmp / "crlf" / "review", "a\r\nb\r\n")
        self.assertEqual(skills.fingerprint(lf), skills.fingerprint(crlf))
        (lf / "x.bin").write_bytes(b"\0a\nb")
        (crlf / "x.bin").write_bytes(b"\0a\r\nb")
        self.assertNotEqual(skills.fingerprint(lf), skills.fingerprint(crlf))

    def test_a_built_in_skill_takes_the_claude_code_version(self):
        (self.tmp / "claude-1000" / "bundled-skills" / "2.1.304" / "abc" / "dataviz").mkdir(parents=True)
        with mock.patch.object(skills, "BUNDLED_ROOT", self.tmp):
            self.assertIsNone(skills.skill_dir("dataviz", self.repo))
            self.assertEqual(skills.record_load(self.conn, "s1", "t5", "dataviz", str(self.repo), "2026-10-20T00:00:00Z"), "cc-2.1.304")
            self.assertIsNone(skills.record_load(self.conn, "s1", "t6", "deleted-skill", str(self.repo), "2026-10-20T00:00:00Z"))

    def test_the_frontmatter_version_is_read_as_the_label(self):
        self.assertEqual(skills.label(self.skill), "1.2.0")

    def test_a_project_skill_wins_over_the_users_and_a_plugin_skill_is_found_by_its_install(self):
        write_skill(self.home / ".claude" / "skills" / "review", "# user copy\n")
        self.assertEqual(skills.skill_dir("review", self.repo / "src"), self.skill.resolve())
        self.assertEqual(skills.skill_dir("review", self.tmp), (self.home / ".claude" / "skills" / "review").resolve())
        user = write_skill(self.tmp / "cache" / "ce" / "3.9" / "skills" / "simplify")
        proj = write_skill(self.tmp / "cache" / "ce" / "4.0" / "skills" / "simplify")
        plugins = self.home / ".claude" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {"ce@market": [
            {"scope": "user", "installPath": str(user.parent.parent)},
            {"scope": "project", "projectPath": str(self.repo), "installPath": str(proj.parent.parent)}]}}))
        self.assertEqual(skills.skill_dir("ce:simplify", self.repo / "src"), proj)
        self.assertEqual(skills.skill_dir("ce:simplify", self.tmp), user)

    def test_a_marked_load_gets_its_exact_version_and_the_files_are_kept_for_a_diff(self):
        self.load("2026-10-10T00:00:00Z", 1, "t1")
        v1 = skills.record_load(self.conn, "s1", "t1", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        self.assertEqual(skills.load_versions(self.conn), [("s1", 1, "review", "2026-10-10T00:00:00Z", v1, True)])
        kept = self.tmp / "data-home" / "data" / "skills" / "review" / v1 / "SKILL.md"
        self.assertEqual(kept.read_text(), (self.skill / "SKILL.md").read_text())

    def test_a_mark_for_a_bare_plugin_skill_name_is_one_version_row_under_the_canonical_name(self):
        plug = write_skill(self.tmp / "cache" / "ce" / "3.9" / "skills" / "simplify")
        plugins = self.home / ".claude" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {"ce@market": [
            {"scope": "user", "installPath": str(plug.parent.parent)}]}}))
        v = skills.record_load(self.conn, "s1", "t1", "simplify", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        self.assertEqual(self.conn.execute("SELECT skill, version FROM skill_versions").fetchall(), [("ce:simplify", v)])
        self.assertEqual(self.conn.execute("SELECT session_id, tool_use_id, skill, version FROM skill_load_versions").fetchall(),
                         [("s1", "t1", "ce:simplify", v)])

    def install(self, *plugs):
        plugins = self.home / ".claude" / "plugins"
        plugins.mkdir(parents=True, exist_ok=True)
        (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {
            f"{p.parent.parent.parent.name}@market": [{"scope": "user", "installPath": str(p.parent.parent)}] for p in plugs}}))

    def test_canonical_name_sees_a_plugin_installed_or_removed_without_a_restart(self):
        cwd = str(self.repo / "src")
        self.assertEqual(skills.canonical_name("simplify", cwd), "simplify")
        plug = write_skill(self.tmp / "cache" / "ce" / "3.9" / "skills" / "simplify")
        self.install(plug)
        self.assertEqual(skills.canonical_name("simplify", cwd), "ce:simplify")
        (plug / "SKILL.md").unlink()
        os.utime(plug.parent, (1, 1))
        self.assertEqual(skills.canonical_name("simplify", cwd), "simplify")

    def test_a_project_or_personal_command_or_skill_is_not_claimed_by_a_plugin(self):
        plug = write_skill(self.tmp / "cache" / "ce" / "3.9" / "skills" / "foo")
        self.install(plug)
        cwd = str(self.repo / "src")
        self.assertEqual(skills.canonical_name("foo", cwd), "ce:foo")
        (self.repo / ".claude" / "commands").mkdir(parents=True)
        (self.repo / ".claude" / "commands" / "foo.md").write_text("do foo")
        self.assertEqual(skills.canonical_name("foo", cwd), "foo")
        (self.repo / ".claude" / "commands" / "foo.md").unlink()
        write_skill(self.home / ".claude" / "skills" / "foo")
        self.assertEqual(skills.canonical_name("foo", cwd), "foo")

    def test_two_plugins_with_the_same_skill_name_leave_the_bare_name_bare(self):
        a = write_skill(self.tmp / "cache" / "ce" / "3.9" / "skills" / "dup")
        b = write_skill(self.tmp / "cache" / "other" / "1.0" / "skills" / "dup")
        self.install(a, b)
        self.assertEqual(skills.canonical_name("dup", str(self.repo)), "dup")
        self.assertEqual(skills.canonical_name("ce:dup", str(self.repo)), "ce:dup")

    def test_an_edit_seen_at_ingest_is_a_new_version_dated_by_the_file_and_later_loads_take_it(self):
        self.load("2026-10-01T00:00:00Z", 1)                     # before tokscope ever saw the skill
        self.load("2026-10-10T00:00:00Z", 2, "t2")
        v1 = skills.record_load(self.conn, "s1", "t2", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        (self.skill / "SKILL.md").write_text("---\nversion: 1.3.0\n---\n# v2 shorter\n")
        os.utime(self.skill / "SKILL.md", (1760400000, 1760400000))  # an mtime in 2025, before v1 was proven in use
        edited = skills._iso(1760400000)
        skills.scan(self.conn, now="2026-10-20T00:00:00+00:00")
        v2 = skills.fingerprint(self.skill)
        first = dict(self.conn.execute("SELECT version, first_seen FROM skill_versions"))
        # the file says 2025, older than v1's proven load, so the change is dated when the scan saw it
        self.assertEqual(first[v2], "2026-10-20T00:00:00+00:00")
        self.assertNotEqual(first[v2], edited)
        self.load("2026-10-21T00:00:00Z", 3, tokens=40)
        got = {i: (v, exact) for _, i, _, _, v, exact in skills.load_versions(self.conn)}
        self.assertEqual(got, {1: (None, False), 2: (v1, True), 3: (v2, False)})

    def test_a_load_a_fraction_after_a_version_started_lands_on_that_version(self):
        v1 = skills.record(self.conn, "review", self.skill, "2026-10-01T00:00:00Z", "scan")
        (self.skill / "SKILL.md").write_text("---\nversion: 1.3.0\n---\n# v2\n")
        v2 = skills.record(self.conn, "review", self.skill, "2026-10-10T10:00:05+00:00", "scan")
        self.load("2026-10-10T10:00:05.400Z", 1)    # same second, but 'Z' sorts after '+00:00' as a string
        self.load("2026-10-10T10:00:04.900Z", 2)
        got = {i: v for _, i, _, _, v, _ in skills.load_versions(self.conn)}
        self.assertEqual(got, {1: v2, 2: v1})
        # a load stamped with a fraction moves first_seen earlier only when it really is earlier
        skills.record(self.conn, "review", self.skill, "2026-10-10T10:00:05.400Z", "load")
        self.assertEqual(self.conn.execute("SELECT first_seen FROM skill_versions WHERE version = ?", (v2,)).fetchone()[0],
                         "2026-10-10T10:00:05+00:00")

    def test_versions_give_loads_and_median_tokens_per_version_and_an_untracked_bucket(self):
        self.load("2026-10-01T00:00:00Z", 1, tokens=900)
        self.load("2026-10-10T00:00:00Z", 2, "t2", tokens=100)
        v1 = skills.record_load(self.conn, "s1", "t2", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        rows = {r["version"]: r for r in skills.versions(self.conn, "review")}
        self.assertEqual((rows[v1]["loads"], rows[v1]["exact"], rows[v1]["tokens_median"], rows[v1]["label"]), (1, 1, 100, "1.2.0"))
        self.assertEqual((rows[None]["loads"], rows[None]["tokens_median"]), (1, 900))

    def test_a_renamed_skill_keeps_its_loads_and_a_split_pair_is_merged(self):
        self.load("2026-10-10T00:00:00Z", 1, "t1")
        v1 = skills.record_load(self.conn, "s1", "t1", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        before = sum(r["loads"] for r in skills.versions(self.conn, "review"))
        # a plugin appears: reingest relabels the call and its requests, the mark still names the old skill
        self.conn.execute("UPDATE skill_calls SET skill = 'ce:review'")
        self.conn.execute("UPDATE requests SET skill = 'ce:review'")
        self.assertEqual(sum(r["loads"] for r in skills.versions(self.conn, "ce:review")), 0)  # the bug
        skills.rekey(self.conn)
        rows = skills.versions(self.conn, "ce:review")
        self.assertEqual((before, sum(r["loads"] for r in rows), rows[0]["version"], rows[0]["exact"]), (1, 1, v1, 1))
        self.assertEqual(self.conn.execute("SELECT skill FROM skill_versions").fetchall(), [("ce:review",)])
        self.assertEqual(self.conn.execute("SELECT skill FROM skill_load_versions").fetchall(), [("ce:review",)])
        skills.rekey(self.conn)  # idempotent
        self.assertEqual(self.conn.execute("SELECT count(*) FROM skill_versions").fetchone(), (1,))

    def test_a_rekey_merges_into_an_existing_row_of_the_new_name(self):
        self.load("2026-10-10T00:00:00Z", 1, "t1")
        v1 = skills.record_load(self.conn, "s1", "t1", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        self.conn.execute("INSERT INTO skill_versions SELECT 'ce:review', version, path, label, '2026-10-12T00:00:00+00:00', "
                          "'2026-10-12T00:00:00+00:00', source, body_hash FROM skill_versions")
        self.conn.execute("UPDATE skill_calls SET skill = 'ce:review'")
        skills.rekey(self.conn)
        self.assertEqual(self.conn.execute("SELECT skill, version, first_seen FROM skill_versions").fetchall(),
                         [("ce:review", v1, "2026-10-10T00:00:00+00:00")])

    def test_failed_loads_are_counted_per_skill_and_are_not_loads(self):
        self.load("2026-10-10T00:00:00Z", 1, "t1")
        v1 = skills.record_load(self.conn, "s1", "t1", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        for tid, sk in (("t2", "review"), ("t3", "nonexistent")):
            self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, phase, source, prompt_idx, tool_use_id, failed) "
                              "VALUES ('s1', '2026-10-11T00:00:00Z', ?, NULL, 'tool', 2, ?, 1)", (sk, tid))
        rows = {(r["skill"], r["version"]): r for r in skills.versions(self.conn)}
        self.assertEqual((rows[("review", v1)]["loads"], rows[("review", v1)]["failed_loads"]), (1, 1))
        self.assertEqual((rows[("nonexistent", None)]["loads"], rows[("nonexistent", None)]["failed_loads"]), (0, 1))
        self.assertEqual(skills.load_versions(self.conn)[0][2], "review")
        self.assertEqual(len(skills.load_versions(self.conn)), 1)

    def test_a_versions_error_rate_counts_failed_calls_and_interrupts_of_its_loads(self):
        self.load("2026-10-01T00:00:00Z", 1, tokens=900)
        self.load("2026-10-10T00:00:00Z", 2, "t2", tokens=100)
        v1 = skills.record_load(self.conn, "s1", "t2", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        calls = [("a", 1, 0, 0), ("b", 1, 1, 0), ("c", 2, 1, 0), ("d", 2, 0, 0), ("e", 2, 0, 1), ("f", 2, 0, 0)]
        self.conn.executemany("INSERT INTO tool_calls (session_id, tool_use_id, prompt_idx, skill, is_error, repeat) "
                              "VALUES ('s1', ?, ?, 'review', ?, ?)", calls)
        self.conn.execute("INSERT INTO turn_events (session_id, prompt_idx, skill, kind) VALUES ('s1', 2, 'review', 'interrupt')")
        rows = {r["version"]: r for r in skills.versions(self.conn, "review")}
        self.assertEqual((rows[v1]["calls"], rows[v1]["errors"], rows[v1]["repeats"], rows[v1]["interrupts"]), (4, 1, 1, 1))
        self.assertEqual(rows[v1]["error_rate"], 0.25)
        self.assertEqual((rows[None]["calls"], rows[None]["errors"]), (2, 1))

    def test_a_skill_mark_from_the_mod_records_the_version_through_the_cli(self):
        db = self.tmp / "data-home" / "data" / "tokscope.db"
        db.parent.mkdir(parents=True)
        mark = {"kind": "tool", "tool": "Skill", "skill": "review", "session_id": "s9", "tool_use_id": "t9",
                "cwd": str(self.repo), "is_error": False}
        with mock.patch("tokscope.cli.DB", db):
            record_skill_versions([json.dumps(mark) + "\n", json.dumps({**mark, "tool": "Agent"}) + "\n"])
        rows = connect(db).execute("SELECT session_id, tool_use_id, skill, version FROM skill_load_versions").fetchall()
        self.assertEqual(rows, [("s9", "t9", "review", skills.fingerprint(self.skill))])


    def test_a_kept_skill_text_dates_the_version_before_its_files_were_rewritten(self):
        same = skills.body_hash(self.skill)
        self.load("2026-10-01T09:00:00Z", 1, "t1", tokens=500, text_hash=same)        # same text, before the rewrite
        self.load("2026-09-20T09:00:00Z", 2, "t0", tokens=900, text_hash="0ther0ther00")  # an older, different text
        os.utime(self.skill / "SKILL.md", (1792800000, 1792800000))                  # files rewritten on 2026-10-25
        skills.scan(self.conn, now="2026-10-26T00:00:00+00:00")
        first = self.conn.execute("SELECT first_seen FROM skill_versions").fetchone()[0]
        self.assertEqual(first, "2026-10-01T09:00:00+00:00")
        got = {i: v for _, i, _, _, v, _ in skills.load_versions(self.conn)}
        self.assertEqual(got[1], skills.fingerprint(self.skill))
        self.assertIsNone(got[2])                       # its text differs, so it is not this version

    def test_a_clean_git_folder_is_dated_by_its_last_commit(self):
        run = lambda *a: subprocess.run(["git", "-C", str(self.repo), *a], check=True, capture_output=True,  # noqa: E731
                                        env={**os.environ, "GIT_AUTHOR_DATE": "2026-09-01T10:00:00+00:00",
                                             "GIT_COMMITTER_DATE": "2026-09-01T10:00:00+00:00"})
        run("init", "-q")
        run("add", ".")
        run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "skill")
        self.assertEqual(skills._evidence(self.conn, "review", self.skill), "2026-09-01T10:00:00+00:00")
        (self.skill / "SKILL.md").write_text("# edited, not committed\n")
        self.assertIsNone(skills._git_date(self.skill))

    def test_the_listing_names_each_skill_once_with_its_versions_under_it(self):
        self.load("2026-10-01T00:00:00Z", 1, tokens=900)
        self.load("2026-10-10T00:00:00Z", 2, "t2", tokens=100)
        v1 = skills.record_load(self.conn, "s1", "t2", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        self.conn.commit()
        with mock.patch("tokscope.cli.DB", self.tmp / "t.db"):
            from tokscope.cli import skills_text
            lines = skills_text().splitlines()
        self.assertEqual(lines[1], "review")
        self.assertTrue(lines[2].startswith("  before tracking"))
        self.assertTrue(lines[3].startswith(f"  {v1} v1.2.0"))

    def test_session_views_name_the_version_each_skill_ran_at(self):
        self.load("2026-10-10T00:00:00Z", 1, "t1", tokens=100)
        v1 = skills.record_load(self.conn, "s1", "t1", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        self.conn.commit()
        from tokscope.cli import session_json, session_text
        self.assertIn(f"review {v1[:6]}", session_text(self.conn, "s1"))
        self.assertEqual(session_json(self.conn, "s1")["skills"], [[f"review {v1[:6]}", 100]])
        self.assertEqual(skills.turn_versions(self.conn, "s1"), {("s1", 1, "review"): (v1, True)})
        out = self.tmp / "r.html"
        write_report(self.tmp / "t.db", out, tasks_dir=self.tmp)
        self.assertIn(f'"skill":"review","tokens":100,"output":0,"usd":0.0,"version":["{v1}",true]', out.read_text())

    def two_versions(self):
        """v1 marked at a load with 1,000 tokens, then an edit carrying a canary, then three loads of 400."""
        self.load("2026-10-10T00:00:00Z", 1, "t1", tokens=1000)
        v1 = skills.record_load(self.conn, "s1", "t1", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        (self.skill / "SKILL.md").write_text("---\nversion: 1.3.0\n---\n# v2\nCANARY-SKILL-RULE keep it short\n")
        for i, tid in ((2, "t2"), (3, "t3"), (4, "t4")):
            self.load(f"2026-10-1{i}T00:00:00Z", i, tid, tokens=400)
            v2 = skills.record_load(self.conn, "s1", tid, "review", str(self.repo / "src"), f"2026-10-1{i}T00:00:00Z")
        self.conn.commit()
        return v1, v2

    def test_the_report_shows_each_version_its_change_and_the_diff(self):
        v1, v2 = self.two_versions()
        out = self.tmp / "r.html"
        write_report(self.tmp / "t.db", out, tasks_dir=self.tmp)
        page = out.read_text()
        self.assertIn('href="#skill-versions">Skill versions<span class="cnt">1</span>', page)
        self.assertIn(f"<code>{v2}</code> v1.3.0", page)
        self.assertIn("▼ 60%", page)                     # 1,000 -> 400 tokens per load
        self.assertIn('title="too few loads to judge"', page)
        self.assertIn(f"Diff <code>{v1}</code> → <code>{v2}</code>", page)
        self.assertIn("<span class='add'>+CANARY-SKILL-RULE keep it short</span>", page)

    def test_newly_tracked_and_unfound_skills_are_told_apart(self):
        self.load("2026-10-01T00:00:00Z", 1, tokens=900)           # before tracking
        self.load("2026-10-10T00:00:00Z", 2, "t2", tokens=300)
        skills.record_load(self.conn, "s1", "t2", "review", str(self.repo / "src"), "2026-10-10T00:00:00Z")
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, phase, source, prompt_idx) "
                          "VALUES ('s1', '2026-10-11T00:00:00Z', 'gone-skill', 'other:gone-skill', 'tool', 3)")
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, skill, input, output, cache_read, "
                          "cache_write_5m, cache_write_1h) VALUES ('s1', 'g', '2026-10-11T00:00:00Z', 'm', 3, 'gone-skill', 5, 0, 0, 0, 0)")
        self.conn.commit()
        out = self.tmp / "r.html"
        write_report(self.tmp / "t.db", out, tasks_dir=self.tmp)
        page = out.read_text()
        self.assertIn("<h3>Tracking started</h3>", page)
        self.assertIn("▼ 67%", page)                                # 900 -> 300
        self.assertIn("No skill has changed since tracking began", page)
        self.assertRegex(page, r"No folder found, so no version[^<]*gone-skill")

    def test_a_shared_report_never_carries_skill_text(self):
        self.two_versions()
        for level in ("redacted", "numbers"):
            out = self.tmp / f"{level}.html"
            write_report(self.tmp / "t.db", out, tasks_dir=self.tmp, level=level)
            page = out.read_text()
            self.assertNotIn("CANARY-SKILL-RULE", page, level)
            self.assertNotIn(str(self.repo), page, level)
            self.assertIn("Skill versions", page)


if __name__ == "__main__":
    unittest.main()
