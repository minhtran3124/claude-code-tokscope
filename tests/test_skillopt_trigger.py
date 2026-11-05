import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope.core import skills
from tokscope.experiments.skillopt import loop, store, suite, trigger
from tests.test_skillopt_loop import FAKE, LoopBase


def prompts(n=40):
    return [{"prompt": f"please summarize notes number {k}", "should_trigger": k % 2 == 0} for k in range(n)]


def write(folder, rows, raw=None):
    (Path(folder) / "evals").mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else json.dumps({"triggers": rows})
    (Path(folder) / "evals" / "triggers.json").write_text(text)


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_missing_file_is_no_evidence(self):
        self.assertEqual(trigger.load(self.dir), [])
        self.assertFalse(trigger.usable([]))
        self.assertIsNone(trigger.file_hash(self.dir))

    def test_bad_shapes_raise(self):
        for raw in ("not json", "[]", '{"triggers": {}}', '{"triggers": [1]}',
                    '{"triggers": [{"prompt": "", "should_trigger": true}]}',
                    '{"triggers": [{"prompt": "x", "should_trigger": "yes"}]}',
                    '{"triggers": [{"prompt": "x", "should_trigger": true}, {"prompt": "x", "should_trigger": false}]}'):
            write(self.dir, None, raw=raw)
            with self.assertRaises(ValueError, msg=raw):
                trigger.load(self.dir)

    def test_load_gives_stable_ids_and_split(self):
        write(self.dir, prompts())
        items = trigger.load(self.dir)
        self.assertEqual(items, trigger.load(self.dir))
        self.assertEqual(len(items), 40)
        self.assertTrue(all(i["id"].startswith("t") and len(i["id"]) == 9 for i in items))
        self.assertTrue(trigger.usable(items))
        self.assertIsNotNone(trigger.file_hash(self.dir))

    def test_split_is_about_60_40_and_fixed_by_text(self):
        rows = prompts(400)
        n_train = sum(trigger.split_of(r["prompt"]) == "train" for r in rows)
        self.assertTrue(200 < n_train < 280, n_train)
        write(self.dir, list(reversed(rows[:50])))
        a = {i["prompt"]: i["split"] for i in trigger.load(self.dir)}
        write(self.dir, rows[:50])
        b = {i["prompt"]: i["split"] for i in trigger.load(self.dir)}
        self.assertEqual(a, b)

    def test_too_few_or_one_sided_is_no_evidence(self):
        write(self.dir, prompts(4))
        self.assertFalse(trigger.usable(trigger.load(self.dir)))
        train_only = [r for r in prompts(200) if trigger.split_of(r["prompt"]) == "train"][:10]
        write(self.dir, train_only)
        self.assertFalse(trigger.usable(trigger.load(self.dir)))

    def test_train_items_never_hold_a_test_prompt(self):
        write(self.dir, prompts())
        items = trigger.load(self.dir)
        shown = {i["prompt"] for i in trigger.train_items(items)}
        test = {i["prompt"] for i in trigger.by_split(items, "test")}
        self.assertTrue(shown and test)
        self.assertFalse(shown & test)
        self.assertEqual(set(trigger.train_items(items)[0]), {"prompt", "should_trigger"})


class DecideTest(unittest.TestCase):
    def test_none_accuracy_fails_instead_of_raising(self):
        self.assertFalse(trigger.decide(None, None))
        self.assertFalse(trigger.decide(0.5, None))
        self.assertFalse(trigger.decide(None, 0.5))
        self.assertTrue(trigger.decide(0.5, 0.5))
        self.assertFalse(trigger.decide(0.6, 0.5))


class ReasonTest(unittest.TestCase):
    def acc(self, cur, dr):
        return {"current": {"test": cur}, "draft": {"test": dr}}

    def test_unmeasured_accuracy_is_not_called_a_drop(self):
        r = loop._trigger_reason(self.acc(0.5, None), False)
        self.assertIn("not measured", r)
        self.assertNotIn("dropped", r)
        self.assertIn("no trigger evidence", r)
        self.assertIn("old description kept", r)
        self.assertNotIn("put back", r)

    def test_measured_reasons_are_unchanged(self):
        self.assertEqual(loop._trigger_reason(self.acc(0.6, 0.5), False),
                         "test accuracy dropped; old description put back")
        self.assertEqual(loop._trigger_reason(self.acc(0.5, 0.5), True),
                         "test accuracy kept; new description kept")


class DescriptionTest(unittest.TestCase):
    def test_normalize_and_changed_ignore_whitespace(self):
        self.assertEqual(trigger.normalize("  a \n  b\tc "), "a b c")
        self.assertFalse(trigger.description_changed("Summarize  notes", "Summarize\nnotes "))
        self.assertTrue(trigger.description_changed("Summarize notes", "Summarize all notes"))

    def test_block_roundtrip_keeps_the_rest(self):
        old = "---\nname: d\ndescription: >\n  Old words\n  more\nother: 1\n---\nbody\n"
        new = "---\nname: d\ndescription: New one\nother: 1\n---\nbody DRAFT\n"
        self.assertEqual(trigger.description_block(old), "description: >\n  Old words\n  more\n")
        out = trigger.with_description(new, trigger.description_block(old))
        self.assertEqual(out, "---\nname: d\ndescription: >\n  Old words\n  more\nother: 1\n---\nbody DRAFT\n")


# the fake claude of test_skillopt_loop, plus trigger prompts ("TRIG YES n" loads the skill unless its description
# says BAD) and three description edits
FAKE_T = FAKE.replace("editor = prompt.startswith", '''if prompt.startswith("TRIG"):
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({"editor": False, "trigger": True, "argv": argv}) + "\\n")
    say({"type": "system", "subtype": "init", "model": "fake", "plugins": []})
    sk = Path(".claude/skills/demo/SKILL.md")
    if sk.exists() and "BAD" not in sk.read_text().split("---")[1] and "YES" in prompt:
        say({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": "demo"}}]}})
    say({"type": "result", "result": "ok", "is_error": False, "total_cost_usd": 0.1, "num_turns": 1, "session_id": "s-%d" % os.getpid(), "usage": {"output_tokens": 5}})
    sys.exit(0)
editor = prompt.startswith''', 1).replace(
    '    Path("SKILL.md").write_text(text)\n    answer', '''    for m, d in (("baddesc", "BAD words"), ("gooddesc", "Summarize notes and minutes"), ("wsdesc", "  Summarize   notes")):
        if mode == m:
            text = text.replace("description: Summarize notes", "description: " + d) + "\\nDRAFT edit %d\\n" % n
    Path("SKILL.md").write_text(text)
    answer''', 1)

ROWS = [{"prompt": f"TRIG {'YES' if k % 2 == 0 else 'NO'} {k}", "should_trigger": k % 2 == 0} for k in range(30)]


class TriggerBase(LoopBase):
    def setUp(self):
        super().setUp()
        fake = Path(self.env["TOKSCOPE_CLAUDE"])
        fake.write_text(FAKE_T)
        self.write_triggers(ROWS)

    def write_triggers(self, rows):
        (self.skill / "evals" / "triggers.json").write_text(json.dumps({"triggers": rows}))

    def desc_of(self, run, v):
        return loop._front_description(run / "versions" / v / "SKILL.md")

    def trigger_lines(self, run, kind):
        return [(l["case"], l["arm"], l["i"]) for l in store.lines(run) if l.get("kind") == kind and l.get("stage") == "trigger"]


class GateTest(TriggerBase):
    def test_worse_description_is_reverted_and_confirm_runs_on_the_reverted_files(self):
        self.set_cfg(editor={"default": "baddesc"})
        run, v = self.go()
        items = trigger.load(run / "suite")
        t = v["trigger"]
        self.assertEqual((t["status"], t["passed"], t["reverted"]), ("ran", False, True))
        self.assertEqual(t["current"]["test"], 1.0)
        self.assertLess(t["draft"]["test"], 1.0)
        for side in ("current", "draft"):
            self.assertEqual(set(t[side]), {"train", "test"})
            self.assertTrue(all(isinstance(x, float) for x in t[side].values()))
        self.assertEqual(t["prompts"], trigger.counts(items))
        text = (run / "versions" / "v1" / "SKILL.md").read_text()
        self.assertEqual(self.desc_of(run, "v1"), "Summarize notes")
        self.assertIn("DRAFT edit 1", text)  # the rest of the draft stays
        self.assertEqual(v["draft_fingerprint"], skills.fingerprint(run / "versions" / "v1"))
        runs = [l for l in store.lines(run) if l.get("kind") == "run"]
        first_confirm = next(k for k, l in enumerate(runs) if l["stage"] == "confirm")
        last_trigger = max(k for k, l in enumerate(runs) if l["stage"] == "trigger")
        self.assertLess(last_trigger, first_confirm)
        # every run has a start and a run line; "triggered" is run.json's load
        self.assertEqual(sorted(self.trigger_lines(run, "start")), sorted(self.trigger_lines(run, "run")))
        self.assertEqual(len(self.trigger_lines(run, "run")), len(items) * 2 * trigger.TRIGGER_RUNS)
        recs = {(r["case"], r["arm"], r["i"]): r for r in store.records(run) if r["stage"] == "trigger"}
        yes = next(i for i in items if i["should_trigger"])
        self.assertNotEqual(recs[(yes["id"], "current", 0)]["load"], "not loaded")
        self.assertEqual(recs[(yes["id"], "v1", 0)]["load"], "not loaded")
        # trigger runs stay out of the benchmark
        b = json.loads((run / "benchmark.json").read_text())
        self.assertEqual({r["stage"] for r in b["runs"]}, {"baseline", "confirm"})
        self.assertTrue(store.index(run) > 0)

    def test_editor_sees_train_prompts_only(self):
        self.set_cfg(editor={"default": "baddesc"})
        run, _ = self.go()
        items = trigger.load(run / "suite")
        ws = store.editor_dir(run, 1)
        blob = "".join(p.read_text(errors="replace") for p in ws.rglob("*") if p.is_file())
        shown = json.loads((ws / "workspace" / "evals" / "triggers.json").read_text())["triggers"]
        self.assertEqual({r["prompt"] for r in shown}, {i["prompt"] for i in trigger.by_split(items, "train")})
        for item in trigger.by_split(items, "test"):
            self.assertNotIn(item["prompt"], blob)
        self.assertIn("may change", (ws / "prompt.md").read_text())

    def test_a_tie_keeps_the_new_description(self):
        self.set_cfg(editor={"default": "gooddesc"})
        run, v = self.go()
        self.assertEqual((v["trigger"]["passed"], v["trigger"]["reverted"]), (True, False))
        self.assertEqual(v["trigger"]["current"], v["trigger"]["draft"])
        self.assertEqual(self.desc_of(run, "v1"), "Summarize notes and minutes")

    def test_a_whitespace_only_change_runs_no_trigger_eval(self):
        self.set_cfg(editor={"default": "wsdesc"})
        run, v = self.go()
        self.assertEqual(trigger.normalize(self.desc_of(run, "v1")), "Summarize notes")
        self.assertEqual(v["trigger"]["status"], "not needed")
        self.assertEqual(self.trigger_lines(run, "start"), [])
        self.assertFalse((run / "results" / "trigger").exists())

    def test_an_edit_that_leaves_the_description_runs_no_trigger_eval(self):
        run, v = self.go()
        self.assertEqual(v["trigger"]["status"], "not needed")
        self.assertEqual(self.trigger_lines(run, "start"), [])

    def test_missing_or_small_file_is_no_evidence_and_the_description_stays_locked(self):
        for rows in (None, ROWS[:4]):
            with self.subTest(rows=rows and len(rows)):
                if rows is None:
                    (self.skill / "evals" / "triggers.json").unlink()
                else:
                    self.write_triggers(rows)
                self.set_cfg(editor={"default": "desc"})
                run, v = self.go()
                self.assertEqual(v["trigger"]["status"], "no trigger evidence")
                self.assertEqual(self.trigger_lines(run, "start"), [])
                res = json.loads((store.editor_dir(run, 1) / "result.json").read_text())
                self.assertEqual(res["reason"], "the description changed (locked)")
                prompt = (store.editor_dir(run, 1) / "prompt.md").read_text()
                self.assertIn("Do not change the `description`", prompt)
                self.assertFalse((store.editor_dir(run, 1) / "workspace" / "evals" / "triggers.json").exists())

    def test_a_bad_file_is_a_load_error_before_any_paid_run(self):
        (self.skill / "evals" / "triggers.json").write_text("{}")
        with self.assertRaises(ValueError):
            loop.start("demo", 50.0, runs=2, cwd=str(self.proj), log=lambda *_: None)
        self.assertEqual(self.calls(), [])

    def test_unusable_frozen_triggers_are_no_evidence_not_a_revert(self):
        self.set_cfg(editor={"default": "baddesc"})
        run, _ = self.go()
        (run / "trigger.json").unlink()
        v1 = run / "versions" / "v1" / "SKILL.md"
        v1.write_text(v1.read_text().replace("Summarize notes", "BAD words", 1))  # a changed description again
        train = [r for r in ROWS if trigger.split_of(r["prompt"]) == "train"]
        write(run / "suite", train)  # plan still says usable, but only train items are left
        ctx = loop.Ctx(run)
        self.assertEqual(ctx.triggers, [])
        loop.trigger_gate(ctx, "v1")
        t = json.loads((run / "trigger.json").read_text())
        self.assertEqual((t["status"], t["passed"], t["reverted"]), ("no trigger evidence", False, True))
        self.assertIn("no trigger evidence, old description kept", t["reason"])
        self.assertNotIn("dropped", t["reason"])
        self.assertEqual(self.desc_of(run, "v1"), "Summarize notes")  # the old description comes back
        self.assertEqual(loop.trigger_block(ctx)["status"], "no trigger evidence")

    def test_lock_refuses_a_changed_frozen_trigger_file(self):
        self.set_cfg(editor={"default": "gooddesc"})
        run, _ = self.go()
        store.check_lock(run)
        frozen = run / "suite" / "evals" / "triggers.json"
        frozen.write_text(frozen.read_text() + " ")
        with self.assertRaises(store.LockError):
            store.check_lock(run)

    def test_resume_after_a_stop_between_the_save_and_the_rewrite_finishes_the_rewrite(self):
        self.set_cfg(editor={"default": "baddesc"})
        run, _ = self.go()
        done = len(self.calls())
        (run / "verdict.json").unlink()
        v1 = run / "versions" / "v1" / "SKILL.md"
        v1.write_text(v1.read_text().replace("Summarize notes", "BAD words", 1))  # the rewrite never happened
        self.assertEqual(self.desc_of(run, "v1"), "BAD words")
        loop.resume(run.name, log=lambda *_: None)
        self.assertEqual(self.desc_of(run, "v1"), "Summarize notes")
        self.assertEqual(len(self.calls()), done)
        v = json.loads((run / "verdict.json").read_text())
        self.assertEqual(v["draft_fingerprint"], skills.fingerprint(run / "versions" / "v1"))
        self.assertEqual(v["trigger"]["reverted"], True)
        loop.regrade(run.name, log=lambda *_: None)
        self.assertEqual(json.loads((run / "verdict.json").read_text())["trigger"], v["trigger"])

    def test_budget_stop_in_the_trigger_stage_then_resume_runs_nothing_twice(self):
        self.set_cfg(editor={"default": "baddesc"})
        real = store.can_spend

        def limited(run, plan):
            return len(self.trigger_lines(run, "start")) < 5 and real(run, plan)

        with mock.patch.object(store, "can_spend", limited):
            run, v = self.go()
        self.assertEqual((v["stopped"], v["stop_stage"]), ("trigger", "trigger"))
        self.assertEqual(v["trigger"]["status"], "not finished")
        self.assertEqual(len(self.trigger_lines(run, "run")), 5)
        self.assertFalse((run / "results" / "confirm").exists())
        (run / "verdict.json").unlink()
        loop.resume(run.name, log=lambda *_: None)
        ran = [(l["stage"], l["case"], l["arm"], l["i"]) for l in store.lines(run) if l.get("kind") == "run"]
        self.assertEqual(len(ran), len(set(ran)))
        v = json.loads((run / "verdict.json").read_text())
        self.assertEqual(v["trigger"]["status"], "ran")
        before = len(self.calls())
        ctx = loop.Ctx(run)
        loop._trigger_runs(ctx, "v1", "test")  # a second call runs nothing
        self.assertEqual(len(self.calls()), before)

    def test_budget_stop_in_the_train_split_is_partial_and_resume_finishes_it(self):
        self.set_cfg(editor={"default": "baddesc"})
        real = store.can_spend

        def limited(run, plan):
            train = {i["id"] for i in loop.Ctx(run).triggers if i["split"] == "train"}
            started = [c for c, _, _ in self.trigger_lines(run, "start") if c in train]
            return len(started) < 2 and real(run, plan)  # stops after the test split, inside train

        with mock.patch.object(store, "can_spend", limited):
            run, v = self.go()
        self.assertEqual(v["stopped"], "trigger")
        t = json.loads((run / "trigger.json").read_text())
        self.assertEqual((v["trigger"]["status"], t["passed"], t["reverted"]), ("partial", False, False))
        self.assertIsNotNone(t["draft"]["test"])
        self.assertIsNone(t["draft"]["train"])  # not finished, and shown as not finished
        (run / "verdict.json").unlink()
        loop.resume(run.name, log=lambda *_: None)
        t2 = json.loads((run / "trigger.json").read_text())
        self.assertEqual(t2["status"], "ran")
        for side in ("current", "draft"):
            self.assertIsNotNone(t2[side]["train"])
        self.assertEqual((t2["draft"]["test"], t2["passed"], t2["reason"]), (t["draft"]["test"], False, t["reason"]))
        ran = [(l["stage"], l["case"], l["arm"], l["i"]) for l in store.lines(run) if l.get("kind") == "run"]
        self.assertEqual(len(ran), len(set(ran)))
        v2 = json.loads((run / "verdict.json").read_text())
        self.assertEqual((v2["trigger"]["status"], v2["stopped"]), ("ran", None))
        self.assertEqual(self.desc_of(run, "v1"), "Summarize notes")


class WorkspaceTest(unittest.TestCase):
    def test_workspace_writes_only_the_given_trigger_items(self):
        tmp = Path(tempfile.mkdtemp())
        skill = tmp / "demo"
        (skill / "evals").mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
        data = {"evals": [{"id": f"c{k}", "prompt": f"p{k}", "checks": [{"type": "answer_regex", "pattern": "x"}]} for k in range(3)]}
        (skill / "evals" / "evals.json").write_text(json.dumps(data))
        live = suite.load_folder(skill, "demo")
        items = trigger.train_items([{"id": "t1", "prompt": "only train", "should_trigger": True, "split": "train"}])
        ws = suite.editor_workspace("demo", tmp / "ws", suite=live, triggers=items)
        self.assertEqual(json.loads((ws / "evals" / "triggers.json").read_text()), {"triggers": items})
        ws2 = suite.editor_workspace("demo", tmp / "ws2", suite=live)
        self.assertFalse((ws2 / "evals" / "triggers.json").exists())


if __name__ == "__main__":
    unittest.main()
