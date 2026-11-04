"""Run one eval case of a skill in an isolated `claude -p` session inside a temp sandbox, then grade it."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from ...core import skills
from ...core.ingest import SKILL_TEXT
from . import grade

TIMEOUT = 15 * 60  # seconds; a run that never ends still ends
MAX_BUDGET_USD = 2.0  # every paid run is capped, like bench and replay


def claude():
    if env := os.environ.get("TOKSCOPE_CLAUDE"):
        return env
    return paths.tool("claude", first=paths.CLAUDE_FIRST) or "claude"


def command(prompt, sandbox, budget=None, model=None):
    """argv of the isolated session. Project settings only, no user MCP, nothing saved, edits allowed in the
    sandbox only, cost capped at `budget` (default MAX_BUDGET_USD), `--model` only when one is given. Never
    --dangerously-skip-permissions."""
    argv = [claude(), "-p", prompt, "--setting-sources", "project", "--strict-mcp-config", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose", "--max-budget-usd", str(budget or MAX_BUDGET_USD),
            "--permission-mode", "acceptEdits", "--add-dir", str(sandbox)]
    return argv + ["--model", model] if model else argv


def _name(label, value):
    value = str(value)
    if not value or value in (".", "..") or "/" in value or "\\" in value or ".." in value:
        raise ValueError(f"{label} {value!r} is not a plain name")
    return value


def load_case(skill, case_id, cwd=None):
    """(case, checks, skill_folder, fixtures). ValueError (a load error) before any paid run."""
    _name("skill", skill)
    _name("case id", case_id)
    if ":" in skill:
        raise ValueError(f"{skill}: a plugin skill cannot be run yet; use a project or personal skill")
    folder = skills.skill_dir(skill, cwd=cwd or os.getcwd())
    if folder is None:
        raise ValueError(f"{skill}: no such skill folder")
    path = folder / "evals" / "evals.json"
    try:
        data = json.loads(path.read_text())
    except OSError:
        raise ValueError(f"{skill}: no {path}") from None
    except ValueError as e:
        raise ValueError(f"{path}: not valid JSON ({e})") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be an object")
    for key in ("evals", "checks"):
        if data.get(key) is not None and not isinstance(data[key], list):
            raise ValueError(f"{path}: {key!r} must be a list")
    cases = [c for c in data.get("evals") or [] if isinstance(c, dict)]
    case = next((c for c in cases if str(c.get("id")) == str(case_id)), None)
    if case is None:
        ids = ", ".join(str(c.get("id")) for c in cases) or "none"
        raise ValueError(f"{skill}: no case {case_id!r} in {path} (cases: {ids})")
    if not case.get("prompt"):
        raise ValueError(f"{skill} case {case_id}: no prompt")
    for key in ("checks", "files"):
        if case.get(key) is not None and not isinstance(case[key], list):
            raise ValueError(f"{skill} case {case_id}: {key!r} must be a list")
    if not all(isinstance(r, str) for r in case.get("files") or []):
        raise ValueError(f"{skill} case {case_id}: 'files' must be a list of paths")
    checks = [grade.check_shape(c) for c in (case.get("checks") or []) + (data.get("checks") or [])]
    if not checks:
        raise ValueError(f"{skill} case {case_id}: no machine checks under 'checks'")
    root, fixtures, seen = folder.resolve(), [], set()
    for rel in case.get("files") or []:
        src = (root / rel).resolve()
        if Path(rel).is_absolute() or not src.is_relative_to(root):
            raise ValueError(f"{skill} case {case_id}: file {rel!r} is outside the skill folder")
        if not src.exists():
            raise ValueError(f"{skill} case {case_id}: file {rel!r} does not exist")
        if src.name in seen:
            raise ValueError(f"{skill} case {case_id}: two files named {src.name!r}")
        seen.add(src.name)
        fixtures.append(src)
    return case, checks, folder, fixtures


def source_folder(skill, folder, version):
    """(folder to pin from, resolved version or None). A version comes from the kept snapshots."""
    if not version:
        return folder, None
    full = skills.resolve_version(skill, version)
    snap = skills.snapshot_dir(skill, full)
    if not snap.is_dir():
        raise ValueError(f"{skill}: no kept files for version {full}")
    return snap, full


def pin_copy(skill, source, sandbox, expect=None):
    """Copy exactly the fingerprint file set of `source` to <sandbox>/.claude/skills/<skill> (so evals/ and its
    checks never reach the model) and check the copy is the same version. Does not use skills.pin and never calls
    skills.check_pinnable: the run uses --setting-sources project, so a personal skill of the same name does not load
    and cannot win over the copy.

    Evidence (one probe of 4 haiku runs during the design, under $0.01): in a temp folder holding a fake copy of
    `create-pr`, `--setting-sources project` loaded that copy over the real personal `create-pr` (21 skills and
    18.3k tokens of context, against 170 skills and 98.6k tokens by default). The opt-in test
    `LiveIsolationTest` repeats it: TOKSCOPE_LIVE=1 python3 -m unittest tests.test_skillopt_runner.LiveIsolationTest"""
    source, dest = Path(source), Path(sandbox) / ".claude" / "skills" / skill
    want = expect or skills.fingerprint(source)
    if want is None:
        raise ValueError(f"{skill}: {source} has no SKILL.md")
    for f in skills._files(source):
        target = dest / f.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    got = skills.fingerprint(dest)
    if got != want:
        raise ValueError(f"{skill}: pinned copy is {got}, wanted {want}")
    return dest, got


def _copy_work(sandbox, dest):
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(Path(sandbox).iterdir()):
        if p.name == ".claude":
            continue
        if p.is_dir() and not p.is_symlink():
            shutil.copytree(p, dest / p.name, symlinks=True)
        else:
            shutil.copy2(p, dest / p.name, follow_symlinks=False)


def _text(content):
    """The text of a tool_result's content: a string, or a list of text blocks."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict)) if isinstance(content, list) else ""


def stream_load(events, skill, want):
    """What loaded, from the stream (a run keeps no transcript, so skills.check_load has nothing to read):
    "ok" when a Skill call names `skill` and a later skill text ("Base directory for this skill: ...", in the
    tool_result or in the text block after it, as Claude Code writes it to a transcript) has body hash `want`,
    "other text" when such a text has another hash, "unconfirmed" when the call returned no skill text, and
    "not loaded" when no Skill call names the skill. Compared the way skills.check_load does."""
    args, texts, called = [None], [], False
    for ev in events:
        content = (ev.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if ev.get("type") == "assistant" and b.get("type") == "tool_use" and b.get("name") == "Skill":
                inp = b.get("input") or {}
                if str(inp.get("skill") or inp.get("name") or "") == skill:
                    called = True
                    args.append(inp.get("args"))
            elif called and ev.get("type") == "user":
                t = _text(b.get("content")) if b.get("type") == "tool_result" else b.get("text") or ""
                if isinstance(t, str) and t.startswith(SKILL_TEXT):
                    texts.append(t)
    if not called:
        return "not loaded"
    if not texts:
        return "unconfirmed"
    ok = any(want in skills.loaded_text_hash(t, a).split() for t in texts for a in args)
    return "ok" if ok else "other text"


def execute(skill, case, checks, fixtures, dest, source=None, model=None, budget=None, expect=None, arm=None,
            version=None):
    """Run one loaded case in a fresh sandbox, write the run folder `dest` (it must not exist) and return it.
    `source` is the folder to pin (the fingerprint files only); None is the no-skill arm: the same flags, no pinned
    copy and no `.claude/skills/<skill>`. run.json carries cost_usd, arm, model and load (from the stream)."""
    t0, lines, proc, timed_out, err = time.time(), [], None, False, None
    sandbox = Path(tempfile.mkdtemp(prefix="tokscope-skillopt-")).resolve()
    run = Path(dest)
    try:
        for src in fixtures:
            if src.is_dir():
                shutil.copytree(src, sandbox / src.name, symlinks=True)
            else:
                shutil.copy2(src, sandbox / src.name)
        pinned, fp, want = None, None, None
        if source is not None:
            pinned, fp = pin_copy(skill, source, sandbox, expect)
            want = skills._sha(skills._body((pinned / "SKILL.md").read_text(errors="replace")))
        run.mkdir(parents=True)  # after the load errors a pin can raise
        argv = command(case["prompt"], sandbox, budget, model)
        try:
            with (run / "stderr.log").open("w") as log, (run / "stream.jsonl").open("w") as stream:
                proc = subprocess.Popen(argv, cwd=sandbox, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=log, text=True)
                def kill():
                    nonlocal timed_out
                    timed_out = True
                    proc.kill()
                timer = threading.Timer(TIMEOUT, kill)
                timer.start()
                try:
                    for line in proc.stdout:
                        stream.write(line)
                        stream.flush()
                        lines.append(line)
                finally:
                    timer.cancel()
                    if proc.poll() is None:
                        proc.kill()
                    proc.stdout.close()
                    proc.wait()
        except OSError as e:  # no claude binary, or the run folder could not be written
            err = str(e) if proc is None else f"could not write stream.jsonl: {e}"
        events = grade.parse(lines)
        grading = grade.grade(events, sandbox, checks)
        if grading["status"] == "INVALID":
            grading["reason"] = err or (f"timeout after {TIMEOUT // 60} min" if timed_out else grading["reason"])
        grade.write(run, grading)
        res = grade._result(events) or {}
        init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
        (run / "final.md").write_text(res.get("result") or "" if grading["status"] != "INVALID" else "")
        (run / "plugins.json").write_text(json.dumps(
            {"init": True, "model": init.get("model"), "plugins": init.get("plugins") or []} if init
            else {"init": False, "model": None, "plugins": []}, indent=2))
        (run / "run.json").write_text(json.dumps({
            "skill": skill, "case": str(case.get("id")), "version": version, "fingerprint": fp,
            "source": str(source) if source is not None else None, "pinned": str(pinned) if pinned else None,
            "arm": arm or ("none" if source is None else "skill"), "model": model,
            "load": "n/a" if source is None else stream_load(events, skill, want), "argv": argv,
            "exit_code": proc.returncode if proc else None,
            "duration_s": round(time.time() - t0, 1), "cost_usd": res.get("total_cost_usd"), "usage": res.get("usage"),
            "num_turns": res.get("num_turns"), "session_id": res.get("session_id"), "status": grading["status"],
            "reason": grading.get("reason")}, indent=2))
        _copy_work(sandbox, run / "files")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    return run


def run_case(skill, case_id, version=None, cwd=None, budget=None):
    """Run one case and return the run folder. ValueError for a load error, before any paid run. `budget` caps the
    cost of this run in USD (default MAX_BUDGET_USD)."""
    if budget is not None and not budget > 0:
        raise ValueError(f"budget {budget!r} must be above 0")
    case, checks, folder, fixtures = load_case(skill, case_id, cwd)
    source, full = source_folder(skill, folder, version)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = paths.home() / "bench" / "skillopt" / "runs" / skill / str(case_id) / stamp
    return execute(skill, case, checks, fixtures, run, source=source, budget=budget, expect=full, version=full)
