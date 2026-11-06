"""Generate a skill's eval draft with one paid `claude -p` call: cases start from its real calls (suite.draft), the model
rewrites each prompt so it runs alone in an empty folder (with small fixture files) and adds the machine checks. It writes
evals/evals.draft.json only; evals.json is never touched (suite.approve does that)."""

import json
import re
import shutil
import subprocess

from . import grade, sandbox, suite

MAX_SKILL_CHARS = 20000
TIMEOUT_S = 600

PROMPT = """You write eval cases for the Claude Code skill "{skill}".

SKILL.md:
<skill>
{body}
</skill>

Cases drawn from real sessions (each has an id and the prompt a user really sent):
<cases>
{cases}
</cases>

Each case runs in an EMPTY temporary folder: not a git repository, no remote, no branches, no earlier conversation, none
of the user's files. A prompt that points at something outside it ("open the PR for my branch", "update it again") cannot
work. So rewrite each prompt so it stands alone:
- keep its intent, so the skill is triggered the way a user would trigger it (do not name the skill);
- put everything the prompt refers to (a diff, notes, a draft) in "files": at most 2 small plain-text files per case,
  name -> content, each under 1500 characters, names without folders;
- then give 1 to 3 checks that a correct run must pass IN THAT FOLDER. Allowed types:
  - answer_regex: {{"type":"answer_regex","pattern":"<regex the final answer must match>"}}
  - file_exists: {{"type":"file_exists","path":"<relative path>"}}
  - file_contains: {{"type":"file_contains","path":"<relative path>","pattern":"<regex>"}}
  - tool_called: {{"type":"tool_called","tool":"<tool name, such as Bash or Read>"}}
  - tool_order: {{"type":"tool_order","tools":["Read","Edit"]}}
  - no_permission_denials: {{"type":"no_permission_denials"}}
Prefer checks that follow from SKILL.md and are hard to pass by accident (not a bare word). Do not require a git repository.
Answer with JSON only, no prose:
{{"cases": {{"<case id>": {{"prompt": "...", "files": {{"notes.md": "..."}}, "checks": [<check>, ...]}}}}}}"""


def _skill_text(folder):
    return (folder / "SKILL.md").read_text(errors="replace")[:MAX_SKILL_CHARS]


def _json_object(text):
    """The first {...} block of the model's answer (it may wrap it in a code fence), or ValueError."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the model did not answer with JSON")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as e:
        raise ValueError(f"the model's JSON did not parse ({e})") from None
    if not isinstance(data, dict) or not isinstance(data.get("cases"), dict):
        raise ValueError("the model's JSON has no 'cases' object")
    return data["cases"]


def command(prompt, budget, model=None):
    """argv of the call: no tools (it only reads the prompt), nothing saved, project settings only, cost capped."""
    argv = [sandbox.claude(), "-p", prompt, "--tools", "", "--setting-sources", "project", "--strict-mcp-config",
            "--no-session-persistence", "--output-format", "json", "--max-budget-usd", str(budget)]
    return argv + ["--model", model] if model else argv


FILE_MAX_CHARS, FILES_MAX = 1500, 2
_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _files(entry):
    """{name: text} the model gave for a case: plain names and small texts only, a bad one is skipped."""
    out = {}
    for name, text in (entry.get("files") or {}).items() if isinstance(entry.get("files"), dict) else ():
        if isinstance(name, str) and _FILE_NAME.match(name) and isinstance(text, str) and 0 < len(text) <= FILE_MAX_CHARS:
            out[name] = text
        if len(out) == FILES_MAX:
            break
    return out


def merge(cases, answer):
    """(cases as the model rewrote them, number of checks dropped for a bad shape, {case id: {name: text}} fixtures).
    A case keeps its id; it takes the model's prompt when that is a non-empty string, and the model's valid checks. A
    case that the model skipped keeps no checks and so stays a problem for suite.load: it is never given a made-up one."""
    out, dropped, fixtures = [], 0, {}
    for case in cases:
        entry = answer.get(str(case["id"]))
        entry = {"checks": entry} if isinstance(entry, list) else entry if isinstance(entry, dict) else {}
        good = []
        for check in entry.get("checks") or []:
            try:
                good.append(grade.check_shape(check))
            except ValueError:
                dropped += 1
        new = dict(case)
        if isinstance(entry.get("prompt"), str) and entry["prompt"].strip():
            new["prompt"] = entry["prompt"].strip()
            new.pop("files", None)  # the real call's files belong to the real prompt, not to the rewritten one
            if fx := _files(entry):
                fixtures[str(case["id"])] = fx
        if good:
            new["checks"] = good
        out.append(new)
    return out, dropped, fixtures


def _write_fixtures(folder, cases, fixtures):
    """Replace each rewritten case's fixtures: the ones suite.draft copied from the real call are removed (they are the
    user's own files and no longer belong to the case), the model's small texts are written under evals/fixtures/<id>/."""
    for case in cases:
        cid = str(case["id"])
        if cid not in fixtures and "files" in case:
            continue  # a case the model did not rewrite keeps what the draft gave it
        if not _FILE_NAME.match(cid):
            continue
        base = folder / "evals" / "fixtures" / cid
        shutil.rmtree(base, ignore_errors=True)
        if cid in fixtures:
            base.mkdir(parents=True)
            for name, text in fixtures[cid].items():
                (base / name).write_text(text)
            case["files"] = [f"evals/fixtures/{cid}/{name}" for name in fixtures[cid]]


def generate(skill, n=5, budget=1.0, model="sonnet", cwd=None, projects_dir=None, run=subprocess.run):
    """Write evals/evals.draft.json with checks from one `claude -p` call. Returns {"path", "cases", "problems",
    "dropped", "cost", "note"}. ValueError when the call fails or answers something unusable (the draft from real calls
    is then already on disk, without checks)."""
    base = suite.draft(skill, n, cwd, projects_dir)  # free; also gives the case ids and fixtures
    folder = suite._folder(skill, cwd)
    prompt = PROMPT.format(skill=skill, body=_skill_text(folder),
                           cases=json.dumps([{"id": c["id"], "prompt": c["prompt"]} for c in base["cases"]], indent=1))
    try:
        proc = run(command(prompt, budget, model), cwd=str(folder), capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ValueError(f"the call took more than {TIMEOUT_S} s and was stopped") from None
    except OSError as e:
        raise ValueError(f"cannot start claude: {e}") from None
    try:
        reply = json.loads(proc.stdout or "{}")
    except ValueError:
        reply = {}
    if proc.returncode != 0 or reply.get("is_error"):
        why = str(reply.get("result") or proc.stderr or "no output").strip().splitlines()[-1:] or ["no output"]
        raise ValueError(f"claude failed: {why[0][:300]}")
    cases, dropped, fixtures = merge(base["cases"], _json_object(str(reply.get("result") or "")))
    _write_fixtures(folder, cases, fixtures)
    suite._atomic_write(base["path"], {"evals": cases, "checks": []})
    problems = suite.load(skill, cwd, suite.DRAFT).problems
    cost = reply.get("total_cost_usd")
    note = f"{len(cases)} cases, {sum(1 for c in cases if c.get('checks'))} with checks" + (f"; {dropped} bad checks dropped" if dropped else "")
    return {"path": base["path"], "cases": cases, "problems": problems, "dropped": dropped,
            "cost": cost if isinstance(cost, (int, float)) else None, "note": note}


def friendly(message):
    """A suite error as (what is wrong, what to do) for a person; the raw text stays available to the caller."""
    m = re.match(r"^(?P<skill>[^:]+): no (?P<path>/.*evals\.json)$", message)
    if m:
        return ("This skill has no eval suite yet.", "Generate one: tokscope drafts cases from your real calls and a model adds the checks. Nothing is approved until you do.")
    if "no machine checks" in message:
        return ("The eval cases have no machine checks, so a run cannot be graded.", "Generate checks, or add a \"checks\" list to each case.")
    if "not valid JSON" in message:
        return ("evals.json is not valid JSON.", "Fix the file, or generate a new draft.")
    return (message, "Run tokscope optimize suite <skill> to see every problem.")
