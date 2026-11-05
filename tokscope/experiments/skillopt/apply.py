"""Approve, reject or revert an optimize run. Approve replaces the skill's fingerprinted files with the measured draft,
checks that the skill's fingerprint is the measured one, and commits when the skill is in git (brief: Approve).
apply.json is written before the first file moves, so a stop mid-write is finished or rolled back by the next command."""
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from ...core import ingest, skills
from ...features import changes as changes_log
from . import stats, store, suite

APPLY, DECISION = "apply.json", "decision.json"
TABLE = """
CREATE TABLE IF NOT EXISTS opt_applied(
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, skill TEXT, kind TEXT, old_fingerprint TEXT,
    new_fingerprint TEXT, commit_sha TEXT, at TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS opt_applied_run ON opt_applied(run_id);
"""


class Refused(ValueError):
    """The action was not done and the skill is as it was (the CLI exits 1). A plain ValueError is a load error (2)."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


# files

def _rels(folder):
    return {p.relative_to(folder).as_posix() for p in skills._files(Path(folder))}


def _planned(folder, src):
    """The relative paths _replace would write or remove."""
    old, new = _rels(folder), _rels(src)
    same = {r for r in old & new if skills._content(Path(folder) / r) == skills._content(Path(src) / r)}
    return sorted((old | new) - same)


def _replace(folder, src):
    """Make the fingerprinted files of `folder` those of `src`: each file goes through a temp file and a rename, files
    `src` lacks are removed. Hidden files, bench folders and large files stay. Returns the changed relative paths."""
    folder, src = Path(folder), Path(src)
    old, new = _rels(folder), _rels(src)
    changed = []
    for rel in sorted(new):
        target = folder / rel
        if target.is_file() and not target.is_symlink() and skills._content(target) == skills._content(src / rel):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tokscope-tmp")
        shutil.copy2(src / rel, tmp)
        os.replace(tmp, target)
        changed.append(rel)
    for rel in sorted(old - new):
        (folder / rel).unlink()
        changed.append(rel)
        parent = (folder / rel).parent
        while parent != folder:  # leave no empty folder of a removed file behind
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return changed


def _restore(folder, skill, fp):
    """Put the kept snapshot of version `fp` back; ApplyError-free: the caller reports."""
    snap = skills.snapshot_dir(skill, fp)
    if skills.fingerprint(snap) != fp:
        return False
    _replace(folder, snap)
    return skills.fingerprint(folder) == fp


# git

def _git(top, *args, check=False):
    try:
        r = subprocess.run(["git", "--literal-pathspecs", "-C", str(top), *args], capture_output=True, text=True,
                           timeout=120, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError) as e:
        if check:
            raise Refused(f"git failed: {e}") from None
        return None
    return r


def _repo(folder):
    """(top, branch) when the folder is in a git work tree; (None, None) outside git. Refused on a detached HEAD."""
    r = _git(folder, "rev-parse", "--show-toplevel")
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None, None
    top = Path(r.stdout.strip()).resolve()
    b = _git(top, "symbolic-ref", "-q", "--short", "HEAD")
    if b is None or b.returncode != 0 or not b.stdout.strip():
        raise Refused(f"{folder}: HEAD is detached; check out a branch first, nothing was changed")
    return top, b.stdout.strip()


def _commit(top, folder, rels, subject, body):
    """Commit only these files; returns the sha. Files git does not know yet are added as intent-to-add so --only sees
    them. On any failure the intent-to-add entries are dropped again and Refused is raised."""
    spec = [(Path(folder) / r).resolve().relative_to(top).as_posix() for r in rels]
    added = []
    try:
        for p in spec:
            if (Path(top) / p).exists() and _git(top, "ls-files", "--error-unmatch", "--", p).returncode != 0:
                r = _git(top, "add", "-N", "--", p)
                if r.returncode != 0:
                    raise Refused(f"git add failed: {r.stderr.strip() or r.stdout.strip()}")
                added.append(p)
        r = _git(top, "commit", "--only", "-m", subject, "-m", body, "--", *spec)
        if r.returncode != 0:
            raise Refused(f"git commit failed: {(r.stderr.strip() or r.stdout.strip())[-400:]}")
    except Refused:
        for p in added:
            _git(top, "reset", "-q", "--", p)
        raise
    return _git(top, "rev-parse", "HEAD").stdout.strip()


def _committed(top, folder, rels, subject):
    """For recovery: the sha when these files have no uncommitted change and HEAD has this subject, else None."""
    spec = [(Path(folder) / r).resolve().relative_to(top).as_posix() for r in rels]
    st = _git(top, "status", "--porcelain", "--", *spec)
    head = _git(top, "log", "-1", "--format=%H%n%s")
    if st is None or head is None or st.stdout.strip() or head.returncode != 0:
        return None
    sha, _, subj = head.stdout.partition("\n")
    return sha.strip() if subj.strip() == subject else None


# the run

def _open(run_id):
    run = store.find_run(run_id)
    plan = store.read_plan(run)
    verdict = _read_json(run / "verdict.json")
    return run, plan, verdict


def _folder(plan):
    """The skill's real path: where the run was started from, else where the skill is found from here."""
    src = plan.get("source")
    if src and (Path(src) / "SKILL.md").is_file():
        return Path(src).resolve()
    found = suite._folder(plan["skill"], None)
    return Path(found).resolve()


def _subject(kind, skill, a, b):
    return f"optimize({skill}): {a} → {b}" if kind == "approve" else f"optimize({skill}): revert {a} → {b}"


def _body(run, kind, verdict, reason):
    lines = []
    if verdict:
        lines.append(f"verdict: {verdict.get('verdict')} ({verdict.get('reason')})")
    lines.append(f"run: {run.name}")
    if reason:
        lines.append(f"reason: {reason}")
    return "\n".join(lines)


def _conn():
    conn = ingest.connect(paths.db())
    conn.executescript(TABLE)
    return conn


def _complete(run, plan, verdict, a, conn=None):
    """Steps 6 and 7 of the brief, once the files hold the target version. Used by an apply and by recovery."""
    skill, folder = a["skill"], Path(a["folder"])
    own = conn is None
    conn = conn or _conn()
    try:
        commit = a.get("commit")
        if a.get("git_top") and commit is None:
            top, subject = Path(a["git_top"]), a["subject"]
            if a.get("recovering"):
                commit = _committed(top, folder, a["changed"], subject)
            if commit is None and (a["changed"] or not a.get("recovering")):
                try:
                    commit = _commit(top, folder, a["changed"], subject, a["body"])
                except Refused:
                    if not _restore(folder, skill, a["from"]):
                        raise Refused(f"the commit failed and the snapshot of {a['from']} could not be restored; "
                                      f"see {run / APPLY}") from None
                    a.update(state="rolled_back", error="commit failed")
                    _write_json(run / APPLY, a)
                    raise
        now = _now()
        skills.record(conn, skill, folder, now, "optimize")
        note = None
        if a["kind"] == "approve":
            try:
                changes_log.add_change(conn, "Optimize applied", skill=skill, at=now)
            except sqlite3.Error as e:  # the apply worked; keep it and note why the row is missing
                note = str(e)
        decision = _read_json(run / DECISION) or {}
        entry = {"old_fingerprint": a["from"], "new_fingerprint": a["to"], "commit": commit, "time": now,
                 "reason": a.get("reason")}
        if note:
            entry["change_error"] = note
        if a["kind"] == "approve":
            decision = {"decision": "approved", "run_id": run.name, "skill": skill,
                        "verdict": (verdict or {}).get("verdict"), **entry}
        else:
            decision["reverted"] = entry
        _write_json(run / DECISION, decision)
        conn.execute("INSERT INTO opt_applied(run_id, skill, kind, old_fingerprint, new_fingerprint, commit_sha, at, reason)"
                     " VALUES (?,?,?,?,?,?,?,?)", (run.name, skill, a["kind"], a["from"], a["to"], commit, now, a.get("reason")))
        conn.commit()
        a.update(state="done", commit=commit)
        a.pop("recovering", None)
        _write_json(run / APPLY, a)
        return {**entry, "kind": a["kind"], "skill": skill, "run_id": run.name, "folder": str(folder)}
    finally:
        if own:
            conn.close()


def recover(run, plan=None, verdict=None):
    """Finish or roll back an apply that stopped half way (apply.json not `done`). Returns a line to print, or None."""
    run = Path(run)
    a = _read_json(run / APPLY)
    if not a or a.get("state") != "writing":
        return None
    folder, skill = Path(a["folder"]), a["skill"]
    now = skills.fingerprint(folder)
    if now == a["to"] and a["from"] != a["to"]:
        a["recovering"] = True
        res = _complete(run, plan or store.read_plan(run), verdict or _read_json(run / "verdict.json"), a)
        return f"finished the interrupted {a['kind']}: {a['from']} → {a['to']}" + (f", commit {res['commit']}" if res["commit"] else "")
    if not _restore(folder, skill, a["from"]):
        raise Refused(f"{skill}: an earlier {a['kind']} stopped half way and version {a['from']} could not be restored; "
                      f"see {run / APPLY}")
    a.update(state="rolled_back", error="interrupted")
    _write_json(run / APPLY, a)
    return f"rolled back the interrupted {a['kind']}: {skill} is at {a['from']}"


def _guard(run, fn):
    store.acquire(run)
    try:
        return fn()
    finally:
        store.release(run)


def _go(run, plan, verdict, kind, folder, src, to_fp, reason):
    """Steps 3 to 7: apply.json, record the old version, replace, check, commit, record."""
    skill = plan["skill"]
    from_fp = skills.fingerprint(folder)
    top, _ = _repo(folder)
    subject = _subject(kind, skill, from_fp, to_fp)
    a = {"kind": kind, "state": "writing", "skill": skill, "folder": str(folder), "from": from_fp, "to": to_fp,
         "src": str(src), "git_top": str(top) if top else None, "subject": subject,
         "body": _body(run, kind, verdict, reason), "reason": reason, "changed": [], "commit": None, "started": _now()}
    conn = _conn()
    try:
        a["changed"] = _planned(folder, src)
        _write_json(run / APPLY, a)
        skills.record(conn, skill, folder, _now(), "optimize")  # keeps the files of the version being replaced
        conn.commit()
        if skills.fingerprint(skills.snapshot_dir(skill, from_fp)) != from_fp:
            a.update(state="rolled_back", error="no snapshot")
            _write_json(run / APPLY, a)
            raise Refused(f"{skill}: the snapshot of {from_fp} could not be kept; nothing was changed")
        _replace(folder, src)
        if skills.fingerprint(folder) != to_fp:
            ok = _restore(folder, skill, from_fp)
            a.update(state="rolled_back", error="fingerprint mismatch")
            _write_json(run / APPLY, a)
            raise Refused(f"{skill}: the fingerprint after writing is not {to_fp}; "
                          + (f"restored {from_fp}" if ok else f"could not restore {from_fp}, see {run / APPLY}"))
        return _complete(run, plan, verdict, a, conn)
    finally:
        conn.close()


def approve(run_id, reason=None):
    """Replace the skill with the run's measured draft. Refused (the skill unchanged): the skill or the draft is not
    the version the run measured, the verdict is Reject, Not enough evidence has no reason, or HEAD is detached."""
    run, plan, verdict = _open(run_id)

    def work():
        note = recover(run, plan, verdict)
        if verdict is None:
            raise Refused(f"{run.name}: no verdict yet; resume the run first")
        v = verdict.get("verdict")
        if v == stats.REJECT:
            raise Refused(f"{run.name}: the verdict is Reject; approve is not offered (reject records it)")
        if v == stats.NOT_ENOUGH and not (reason or "").strip():
            raise Refused(f"{run.name}: Not enough evidence needs --reason <text>")
        if v not in (stats.APPLY, stats.NOT_ENOUGH):
            raise Refused(f"{run.name}: unknown verdict {v!r}")
        draft, want = verdict.get("draft_version"), verdict.get("draft_fingerprint")
        if not draft or not want:
            raise Refused(f"{run.name}: the run has no draft to apply")
        folder = _folder(plan)
        if skills.fingerprint(folder) != plan["base_fingerprint"]:
            raise Refused(f"{plan['skill']}: the skill changed after this run (now {skills.fingerprint(folder)}, "
                          f"the run measured {plan['base_fingerprint']}); run optimize again")
        src = run / "versions" / draft
        if skills.fingerprint(src) != want:
            raise Refused(f"{run.name}: the draft {draft} changed after it was confirmed; run optimize again")
        if want == plan["base_fingerprint"]:
            raise Refused(f"{run.name}: the draft is the same version as the skill; nothing to apply")
        res = _go(run, plan, verdict, "approve", folder, src, want, (reason or "").strip() or None)
        res["recovered"] = note
        return res

    return _guard(run, work)


def revert(run_id):
    """Put the version the run replaced back, through the same checks and commit. Only after an approve."""
    run, plan, verdict = _open(run_id)

    def work():
        note = recover(run, plan, verdict)
        d = _read_json(run / DECISION)
        if not d or d.get("decision") != "approved":
            raise Refused(f"{run.name}: this run was not approved; there is nothing to revert")
        if d.get("reverted"):
            raise Refused(f"{run.name}: already reverted")
        old, new = d["old_fingerprint"], d["new_fingerprint"]
        folder = _folder(plan)
        if skills.fingerprint(folder) != new:
            raise Refused(f"{plan['skill']}: the skill is not the approved version {new} any more "
                          f"(now {skills.fingerprint(folder)}); revert is refused")
        snap = skills.snapshot_dir(plan["skill"], old)
        if skills.fingerprint(snap) != old:
            raise Refused(f"{plan['skill']}: the kept files of {old} are missing or changed; revert is refused")
        res = _go(run, plan, verdict, "revert", folder, snap, old, None)
        res["recovered"] = note
        return res

    return _guard(run, work)


def reject(run_id):
    """Record that the owner rejected the run. Always allowed, except after an approve (use revert)."""
    run, plan, verdict = _open(run_id)

    def work():
        note = recover(run, plan, verdict)
        d = _read_json(run / DECISION)
        if d and d.get("decision") == "approved" and not d.get("reverted"):
            raise Refused(f"{run.name}: it was approved; use revert to undo it")
        now = _now()
        decision = {"decision": "rejected", "run_id": run.name, "skill": plan["skill"],
                    "verdict": (verdict or {}).get("verdict"), "time": now}
        _write_json(run / DECISION, decision)
        conn = _conn()
        try:
            conn.execute("INSERT INTO opt_applied(run_id, skill, kind, old_fingerprint, new_fingerprint, commit_sha, at, reason)"
                         " VALUES (?,?,?,?,?,?,?,?)", (run.name, plan["skill"], "reject", None, None, None, now, None))
            conn.commit()
        finally:
            conn.close()
        return {**decision, "kind": "reject", "recovered": note}

    return _guard(run, work)


def report(res):
    """Lines to print."""
    if res["kind"] == "reject":
        return [f"rejected {res['run_id']}; {res['skill']} is unchanged"]
    out = []
    if res.get("recovered"):
        out.append(res["recovered"])
    verb = "approved" if res["kind"] == "approve" else "reverted"
    out.append(f"{verb} {res['run_id']}: {res['skill']} {res['old_fingerprint']} → {res['new_fingerprint']}")
    out.append(f"commit {res['commit']}" if res["commit"] else "no commit (not in git); the old version is kept in the snapshot")
    if res.get("change_error"):
        out.append(f"note: the changes row was not written ({res['change_error']})")
    return out
