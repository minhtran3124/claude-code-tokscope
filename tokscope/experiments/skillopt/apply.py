"""Approve, reject or revert an optimize run. Approve installs the measured draft so the installed fingerprint equals
the measured one, commits only the skill's files when the skill is in git, and records the version, the change and the
decision. Any failure, or a stop at any point, leaves the skill at its old fingerprint (apply.json says how to finish
or undo an apply that was cut short; every command runs `recover` first)."""
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from ...core import ingest, skills
from ...features import changes
from . import stats, store, suite

APPLY_JSON, DECISION_JSON = "apply.json", "decision.json"
TABLE = """
CREATE TABLE IF NOT EXISTS opt_applied(
    run_id TEXT, skill TEXT, action TEXT, old_version TEXT, new_version TEXT, commit_sha TEXT, verdict TEXT,
    reason TEXT, at TEXT, PRIMARY KEY(run_id, action, at));
"""
TMP = ".{}.tokscope-tmp-{}"  # hidden, so a leftover never changes the fingerprint


class Refused(ValueError):
    """The apply was refused or undone; the skill is at its old fingerprint (the CLI exits 2)."""


# small helpers

def _now(now):
    if isinstance(now, str):
        return now
    return (now or datetime.now(timezone.utc)).isoformat()


def _write_json(path, data):
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _db():
    conn = ingest.connect(paths.db())
    conn.executescript(TABLE)
    return conn


def _files(folder):
    return {p.relative_to(folder).as_posix(): p for p in skills._files(Path(folder))}


def _clean_tmp(folder):
    for p in Path(folder).rglob(".*.tokscope-tmp-*"):
        if p.is_file():
            p.unlink(missing_ok=True)


def _replace(folder, src):
    """Make the covered files of `folder` (the fingerprint's file set) the covered files of `src`. Removed files go
    first (so a file can become a folder); each new file is written beside its target and renamed into place.
    Uncovered files (evals/, hidden, over 1 MB) are never listed, so never touched."""
    folder, src = Path(folder), Path(src)
    want, have = _files(src), _files(folder)
    for rel in sorted(set(have) - set(want)):
        have[rel].unlink(missing_ok=True)
        parent = have[rel].parent
        while parent != folder:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    for rel, f in want.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / TMP.format(target.name, os.getpid())
        shutil.copyfile(f, tmp)
        shutil.copymode(f, tmp)
        os.replace(tmp, target)
    _clean_tmp(folder)


def _restore(state):
    """Put the old version back from its snapshot; Refused (state kept) when that cannot be done."""
    snap = skills.snapshot_dir(state["skill"], state["old"])
    folder = Path(state["folder"])
    if skills.fingerprint(snap) != state["old"]:
        raise Refused(f"{state['skill']}: cannot restore {state['old']}: the snapshot {snap} is missing or changed; "
                      f"copy it over {folder} by hand, then delete {state['run_dir']}/{APPLY_JSON}")
    try:
        _replace(folder, snap)
    except OSError as e:
        raise Refused(f"{state['skill']}: restoring {state['old']} failed ({e}); copy {snap} over {folder} by hand") from None
    if skills.fingerprint(folder) != state["old"]:
        raise Refused(f"{state['skill']}: restoring {state['old']} did not reach it; copy {snap} over {folder} by hand")


# git

def _git(top, *args):
    env = {**os.environ, "GIT_LITERAL_PATHSPECS": "1"}
    try:
        return subprocess.run(["git", "-C", str(top), *args], capture_output=True, text=True, env=env)
    except FileNotFoundError:  # git is not installed: treat the folder as not in git
        return subprocess.CompletedProcess(args, 127, "", "git not found")


def _toplevel(folder):
    r = _git(folder, "rev-parse", "--show-toplevel")
    return Path(r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def _head(top):
    r = _git(top, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def _commit_paths(state):
    top = Path(state["git_top"])
    cand = state["paths"]
    tracked = set(_git(top, "ls-files", "-z", "--", *cand).stdout.split("\0"))
    keep = [p for p in cand if (top / p).exists() or p in tracked]
    return [p for p in keep if _git(top, "check-ignore", "-q", "--", p).returncode != 0]


def _found_commit(state):
    """The commit this apply made (its message names the run), looked for after head_before; None when there is none."""
    top = state.get("git_top")
    if not top:
        return None
    rng = f"{state['head_before']}..HEAD" if state.get("head_before") else "HEAD"
    r = _git(top, "log", rng, "--format=%H%x1f%B%x1e")
    if r.returncode != 0:
        return None
    for entry in r.stdout.split("\x1e"):
        sha, _, body = entry.strip().partition("\x1f")
        if sha and f"Run: {state['run_id']}" in body.splitlines() and f"Action: {state['action']}" in body.splitlines():
            return sha
    return None


def _commit(state):
    if not state.get("git_top"):
        return None
    top = Path(state["git_top"])
    keep = _commit_paths(state)
    if not keep:
        return None
    body = [f"Verdict: {state['verdict']}", f"Run: {state['run_id']}", f"Action: {state['action']}"]
    if state.get("reason"):
        body.append(f"Reason: {state['reason']}")
    r = _git(top, "add", "-A", "--", *keep)
    if r.returncode == 0:
        r = _git(top, "commit", "--only", "-m", state["subject"], "-m", "\n".join(body), "--", *keep)
    if r.returncode != 0:
        _git(top, "reset", "-q", "--", *state["paths"])
        tail = (r.stderr.strip() or r.stdout.strip()).splitlines()[-3:]
        raise Refused(f"{state['skill']}: git commit failed, skill left at {state['old']}: {' | '.join(tail)}")
    return _head(top)


# records

def _finish(state, conn):
    """Everything after the files and the commit: the new version, the change, opt_applied, decision.json. Safe to run
    twice (recover), because each row is looked for first."""
    run_dir, skill, folder = Path(state["run_dir"]), state["skill"], Path(state["folder"])
    skills.record(conn, skill, folder, state["at"], "optimize")
    conn.commit()
    note = (f"Optimize {'approved' if state['action'] == 'approve' else 'reverted'}: "
            f"{state['old']} → {state['new']} ({state['run_id']})")
    change_error = None
    conn.executescript(changes.CHANGES_SCHEMA)
    have = conn.execute("SELECT 1 FROM changes WHERE at = ? AND skill = ? AND note = ?", (state["at"], skill, note)).fetchone()
    if not have:
        try:
            changes.add_change(conn, note, skill=skill, at=state["at"])
        except sqlite3.Error as e:  # the version and the files stand; the marker is the only thing missing (#181)
            change_error = f"{type(e).__name__}: {e}"
    conn.execute("INSERT OR IGNORE INTO opt_applied VALUES (?,?,?,?,?,?,?,?,?)",
                 (state["run_id"], skill, state["action"], state["old"], state["new"], state.get("commit_sha"),
                  state["verdict"], state.get("reason"), state["at"]))
    conn.commit()
    record = {"decision": state["action"], "run_id": state["run_id"], "skill": skill, "verdict": state["verdict"],
              "reason": state.get("reason"), "old_fingerprint": state["old"], "new_fingerprint": state["new"],
              "commit_sha": state.get("commit_sha"), "at": state["at"]}
    if change_error:
        record["change_error"] = change_error
    _push(run_dir, record)
    (run_dir / APPLY_JSON).unlink(missing_ok=True)
    return record


def _push(run_dir, record):
    """Write decision.json with the earlier decision(s) kept in history."""
    prev = _read_json(Path(run_dir) / DECISION_JSON)
    history = []
    if prev:
        history = list(prev.get("history", []))
        history.append({k: v for k, v in prev.items() if k != "history"})
    _write_json(Path(run_dir) / DECISION_JSON, {**record, "history": history})


def _latest_applied(run_dir):
    """The latest approve or revert of a run (rejects are ignored), or None."""
    d = _read_json(Path(run_dir) / DECISION_JSON)
    if not d:
        return None
    for rec in [d, *reversed(d.get("history", []))]:
        if rec.get("decision") in ("approve", "revert"):
            return rec
    return None


# locks and recovery

class _Locked:
    """One lock for every approve, reject, revert and recovery, so a recovery never undoes an apply that is running."""

    def __enter__(self):
        d = store.runs_dir().parent / ".apply"
        d.mkdir(parents=True, exist_ok=True)
        self.dir = d
        store.acquire(d)
        return self

    def __exit__(self, *exc):
        store.release(self.dir)


def recover(log=print):
    """Finish or undo every apply that stopped half way. Returns the run ids it handled."""
    done = []
    for f in sorted(store.runs_dir().glob(f"*/{APPLY_JSON}")):
        state = _read_json(f)
        if not state or "folder" not in state:
            f.unlink(missing_ok=True)
            continue
        folder = Path(state["folder"])
        live = skills.fingerprint(folder)
        committed = state.get("phase") == "committed"  # files installed and committed (or nothing to commit)
        sha = state.get("commit_sha") if committed else None
        sha = sha or _found_commit(state)
        if sha or committed:
            if live != state["new"]:
                what = f"commit {sha} was made" if sha else "the apply was installed"
                raise Refused(f"{state['run_id']}: {what} but {folder} no longer matches it "
                              f"(fingerprint {live}); fix the folder by hand, then delete {f}")
            conn = _db()
            try:
                _finish({**state, "commit_sha": sha}, conn)
            finally:
                conn.close()
            log(f"tokscope: finished the interrupted {state['action']} of {state['run_id']}")
        else:
            if state.get("git_top"):
                _git(state["git_top"], "reset", "-q", "--", *state["paths"])
            if live != state["old"]:
                _restore(state)
            _clean_tmp(folder)
            f.unlink(missing_ok=True)
            log(f"tokscope: undid the interrupted {state['action']} of {state['run_id']}; {state['skill']} is at {state['old']}")
        done.append(state["run_id"])
    return done


# the pipeline shared by approve and revert

def _install(run, folder, action, src, cur_fp, target_fp, verdict, reason, subject, now):
    run, folder = Path(run), Path(folder)
    skill = store.read_plan(run)["skill"]
    at = _now(now)
    top = _toplevel(folder)
    head_before = None
    if top:
        if _git(top, "symbolic-ref", "-q", "HEAD").returncode != 0:
            raise Refused(f"{skill}: git is on a detached HEAD; check out a branch first")
        head_before = _head(top)
    have, want = _files(folder), _files(src)
    for rel in want:  # a covered draft file must not land on a file the fingerprint does not cover (over 1 MB)
        if (folder / rel).is_file() and rel not in have:
            raise Refused(f"{skill}: {rel} exists in the skill but is not covered by the fingerprint (over 1 MB); "
                          f"move it first")
    conn = _db()
    try:
        skills.record(conn, skill, folder, at, "optimize")
        conn.commit()
    finally:
        conn.close()
    if skills.fingerprint(skills.snapshot_dir(skill, cur_fp)) != cur_fp:
        raise Refused(f"{skill}: could not keep a snapshot of {cur_fp}; nothing was changed")
    rel_top = (lambda rel: Path(os.path.relpath(folder / rel, top)).as_posix()) if top else (lambda rel: rel)
    state = {"action": action, "run_id": run.name, "run_dir": str(run), "skill": skill, "folder": str(folder),
             "old": cur_fp, "new": target_fp, "source": str(src), "git_top": str(top) if top else None,
             "head_before": head_before, "phase": "writing", "at": at, "verdict": verdict, "reason": reason,
             "subject": subject, "paths": sorted({rel_top(r) for r in {*have, *want}})}
    _write_json(run / APPLY_JSON, state)
    try:
        _replace(folder, src)
    except OSError as e:
        _restore(state)
        (run / APPLY_JSON).unlink(missing_ok=True)
        raise Refused(f"{skill}: writing the skill failed ({e}); it is back at {cur_fp}") from None
    if skills.fingerprint(folder) != target_fp:
        _restore(state)
        (run / APPLY_JSON).unlink(missing_ok=True)
        raise Refused(f"{skill}: the installed files do not match fingerprint {target_fp}; it is back at {cur_fp}")
    state["phase"] = "written"
    _write_json(run / APPLY_JSON, state)
    try:
        state["commit_sha"] = _commit(state)
    except Refused:
        _restore(state)
        (run / APPLY_JSON).unlink(missing_ok=True)
        raise
    state["phase"] = "committed"
    _write_json(run / APPLY_JSON, state)
    conn = _db()
    try:
        return _finish(state, conn)
    finally:
        conn.close()


def _run_lock(run_id):
    run = store.find_run(run_id)
    store.acquire(run)  # refuses while `run` or `resume` holds it
    return run


def approve(run_id, reason=None, cwd=None, now=None):
    with _Locked():
        recover()
        run = _run_lock(run_id)
        try:
            v = _read_json(run / "verdict.json")
            if not v:
                raise Refused(f"{run_id}: no verdict.json; the run has not finished")
            if v.get("verdict") == stats.REJECT:
                raise Refused(f"{run_id}: the verdict is {stats.REJECT}; nothing to apply")
            if v.get("verdict") == stats.NOT_ENOUGH and not (reason or "").strip():
                raise Refused(f"{run_id}: the verdict is {stats.NOT_ENOUGH}; give --reason to approve it anyway")
            if v.get("verdict") not in (stats.APPLY, stats.NOT_ENOUGH):
                raise Refused(f"{run_id}: unknown verdict {v.get('verdict')!r}")
            if not (v.get("draft_version") and v.get("draft_fingerprint")):
                raise Refused(f"{run_id}: no draft to apply")
            folder = suite._folder(store.read_plan(run)["skill"], cwd)
            live = skills.fingerprint(folder)
            last = _latest_applied(run)
            if live == v["draft_fingerprint"] and last and last.get("decision") == "approve":
                raise Refused(f"{run_id}: already approved ({live}); `tokscope optimize revert {run_id}` undoes it")
            if live != v["base_fingerprint"]:
                raise Refused(f"{run_id}: the skill was edited after the run (now {live}, measured {v['base_fingerprint']}); "
                              f"run the optimize again")
            draft = run / "versions" / v["draft_version"]
            if skills.fingerprint(draft) != v["draft_fingerprint"]:
                raise Refused(f"{run_id}: the draft in {draft} changed after the run; run the optimize again")
            subject = f"optimize({v['skill']}): {live} → {v['draft_fingerprint']}"
            return _install(run, folder, "approve", draft, live, v["draft_fingerprint"], v["verdict"],
                            (reason or "").strip() or None, subject, now)
        finally:
            store.release(run)


def reject(run_id, reason=None, cwd=None, now=None):
    with _Locked():
        recover()
        run = _run_lock(run_id)
        try:
            plan = store.read_plan(run)
            v = _read_json(run / "verdict.json") or {}
            try:
                fp = skills.fingerprint(suite._folder(plan["skill"], cwd))
            except ValueError:
                fp = None
            record = {"decision": "reject", "run_id": run.name, "skill": plan["skill"], "verdict": v.get("verdict"),
                      "reason": (reason or "").strip() or None, "old_fingerprint": fp, "new_fingerprint": fp,
                      "commit_sha": None, "at": _now(now)}
            _push(run, record)
            return {**record, "history": []}
        finally:
            store.release(run)


def revert(run_id, cwd=None, now=None):
    with _Locked():
        recover()
        run = _run_lock(run_id)
        try:
            last = _latest_applied(run)
            if not last or last.get("decision") != "approve":
                raise Refused(f"{run_id}: nothing to revert; the run has no approve that is still applied")
            skill = last["skill"]
            folder = suite._folder(skill, cwd)
            live = skills.fingerprint(folder)
            if live != last["new_fingerprint"]:
                raise Refused(f"{run_id}: the skill was edited after the approve (now {live}, approved "
                              f"{last['new_fingerprint']}); revert by hand")
            snap = skills.snapshot_dir(skill, last["old_fingerprint"])
            if skills.fingerprint(snap) != last["old_fingerprint"]:
                raise Refused(f"{run_id}: the old version {last['old_fingerprint']} is not kept at {snap}")
            subject = f"optimize({skill}): {live} → {last['old_fingerprint']} (revert {run.name})"
            return _install(run, folder, "revert", snap, live, last["old_fingerprint"], last["verdict"], None, subject, now)
        finally:
            store.release(run)
