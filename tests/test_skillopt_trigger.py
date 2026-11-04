import json
import tempfile
import unittest
from pathlib import Path

from tokscope.experiments.skillopt import trigger


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


if __name__ == "__main__":
    unittest.main()
