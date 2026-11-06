"""Generate a skill's eval draft with one paid `claude -p` call: cases come from its real calls (suite.draft), the model adds
the machine checks. It writes evals/evals.draft.json only; evals.json is never touched (suite.approve does that)."""

import json
import re
import subprocess

from . import grade, sandbox, suite

MAX_SKILL_CHARS = 20000
TIMEOUT_S = 600

PROMPT = """You write machine checks for an eval suite of the Claude Code skill "{skill}".

SKILL.md:
<skill>
{body}
</skill>

Cases (each has an id and the prompt a user really sent):
<cases>
{cases}
</cases>

For EACH case give 1 to 3 checks that a correct run must pass. Allowed check types and their keys:
- answer_regex: {{"type":"answer_regex","pattern":"<regex the final answer must match>"}}
- file_exists: {{"type":"file_exists","path":"<relative path>"}}
- file_contains: {{"type":"file_contains","path":"<relative path>","pattern":"<regex>"}}
- tool_called: {{"type":"tool_called","tool":"<tool name, such as Bash or Read>"}}
- tool_order: {{"type":"tool_order","tools":["Read","Edit"]}}
- no_permission_denials: {{"type":"no_permission_denials"}}
Prefer checks that follow from SKILL.md and are hard to pass by accident. Use no_permission_denials only as an extra.
Answer with JSON only, no prose: {{"cases": {{"<case id>": [<check>, ...]}}}}"""


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


def merge(cases, answer):
    """(cases with the model's valid checks, number of checks dropped for a bad shape). A case that the model skipped
    keeps no checks and so stays a problem for suite.load: it is never given a made-up one."""
    out, dropped = [], 0
    for case in cases:
        good = []
        for check in answer.get(str(case["id"])) or []:
            try:
                good.append(grade.check_shape(check))
            except ValueError:
                dropped += 1
        out.append({**case, "checks": good} if good else dict(case))
    return out, dropped


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
    cases, dropped = merge(base["cases"], _json_object(str(reply.get("result") or "")))
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
