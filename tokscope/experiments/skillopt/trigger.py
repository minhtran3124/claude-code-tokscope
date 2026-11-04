"""Trigger eval for a changed skill description: `<skill>/evals/triggers.json` holds should-trigger and
should-not-trigger prompts, split by a hash of the prompt text into train (60%) and test (40%). The editor sees train
prompts only. A draft that changes the description must not lower test-split accuracy; else the old description comes
back. Pure functions here; the paid runs go through loop.run_one (stage `trigger`)."""
import hashlib
import json
from pathlib import Path

from ...core import skills

NAME = "triggers.json"
STAGE = "trigger"
MIN_PROMPTS = 5
TRAIN_PCT = 60
TRIGGER_RUNS = 3
SPLITS = ("train", "test")


def _digest(prompt):
    return hashlib.sha256(prompt.encode()).hexdigest()[:8]


def prompt_id(prompt):
    return "t" + _digest(prompt)


def split_of(prompt):
    """"train" or "test", fixed by the prompt text."""
    return "train" if int(_digest(prompt), 16) % 100 < TRAIN_PCT else "test"


def load(folder):
    """Items [{id, prompt, should_trigger, split}] from `<folder>/evals/triggers.json`; [] when the file is missing.
    ValueError for a file that is not valid."""
    path = Path(folder) / "evals" / NAME
    try:
        text = path.read_text()
    except OSError:
        return []
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{path}: not valid JSON ({e})") from None
    rows = data.get("triggers") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected an object with a 'triggers' list")
    items, seen = [], set()
    for k, row in enumerate(rows):
        if (not isinstance(row, dict) or not isinstance(row.get("prompt"), str) or not row["prompt"].strip()
                or not isinstance(row.get("should_trigger"), bool)):
            raise ValueError(f"{path}: triggers[{k}] needs a non-empty 'prompt' and a boolean 'should_trigger'")
        pid = prompt_id(row["prompt"])
        if pid in seen:
            raise ValueError(f"{path}: triggers[{k}] repeats an earlier prompt")
        seen.add(pid)
        items.append({"id": pid, "prompt": row["prompt"], "should_trigger": row["should_trigger"],
                      "split": split_of(row["prompt"])})
    return items


def file_hash(folder):
    """sha256 of the file's bytes, None when there is no file."""
    try:
        return hashlib.sha256((Path(folder) / "evals" / NAME).read_bytes()).hexdigest()
    except OSError:
        return None


def by_split(items, name):
    return [i for i in items if i["split"] == name]


def usable(items):
    """Enough prompts, and both splits non-empty (the test split decides, the train split guides the editor)."""
    return len(items) >= MIN_PROMPTS and all(by_split(items, s) for s in SPLITS)


def train_items(items):
    """What the editor may see: train prompts only, as they are written in the file."""
    return [{"prompt": i["prompt"], "should_trigger": i["should_trigger"]} for i in by_split(items, "train")]


def counts(items):
    return {s: len(by_split(items, s)) for s in SPLITS}


def normalize(text):
    return " ".join((text or "").split())


def description_changed(old, new):
    return normalize(old) != normalize(new)


def correct(record, item):
    """A run is right when it was valid and the skill was loaded exactly when it should be."""
    if record["status"] != "ok":
        return False
    return (record["load"] != "not loaded") == item["should_trigger"]


def accuracy(records, items, arm, split):
    """Correct runs over all expected runs of `arm` on `split`; None when no prompt is there or a run is missing."""
    mine = by_split(items, split)
    if not mine:
        return None
    done = {(r["case"], r["i"]): r for r in records if r["stage"] == STAGE and r["arm"] == arm}
    right = 0
    for item in mine:
        for i in range(TRIGGER_RUNS):
            r = done.get((item["id"], i))
            if r is None:
                return None
            right += correct(r, item)
    return right / (len(mine) * TRIGGER_RUNS)


# the description block of a SKILL.md

def _block_span(lines):
    """(start, end) line indexes of the frontmatter `description` block (its continuation lines too), None when
    there is none."""
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    try:
        close = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---")
    except StopIteration:
        return None
    start = next((i for i in range(1, close) if lines[i].startswith("description:")), None)
    if start is None:
        return None
    end = start + 1
    while end < close and (not lines[end].strip() or lines[end][:1] in (" ", "\t")):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():  # trailing blank lines are not part of the value
        end -= 1
    return start, end


def description_block(text):
    """The raw `description` lines of a SKILL.md, None when there is none."""
    lines = text.splitlines(keepends=True)
    span = _block_span(lines)
    return "".join(lines[span[0]:span[1]]) if span else None


def with_description(text, block):
    """`text` with its description block replaced by the raw `block`; the rest of the file is untouched."""
    lines = text.splitlines(keepends=True)
    span = _block_span(lines)
    if span is None:
        raise ValueError("SKILL.md has no description to put back")
    if not block.endswith("\n") and span[1] < len(lines):
        block += "\n"
    return "".join(lines[:span[0]]) + block + "".join(lines[span[1]:])


def revert_description(draft_dir, v0_dir):
    """Put v0's description block into the draft's SKILL.md (tmp file, then replace). Idempotent."""
    draft, old = Path(draft_dir) / "SKILL.md", Path(v0_dir) / "SKILL.md"
    block = description_block(old.read_text(errors="replace"))
    if block is None:
        raise ValueError(f"{old}: no description")
    new = with_description(draft.read_text(errors="replace"), block)
    if new != draft.read_text(errors="replace"):
        tmp = draft.with_name(draft.name + ".tmp")
        tmp.write_text(new)
        tmp.replace(draft)
    return skills.fingerprint(draft_dir)


def decide(current_test, draft_test):
    """Pass when the draft's test accuracy is not below the current one's (a tie passes). An accuracy that is None
    (no test prompt, or a missing run) cannot be compared, so the draft fails and the old description is put back."""
    if current_test is None or draft_test is None:
        return False
    return draft_test >= current_test
