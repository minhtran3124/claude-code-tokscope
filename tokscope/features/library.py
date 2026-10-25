"""Your own skills, to read: the ones in ~/.claude/skills and in the .claude/skills folder of each project a
transcript ran in. Plugin and built-in skills live elsewhere and are never listed.

A skill there counts as installed, not yours, when an installer left a trace: a link into ~/.agents (npx skills), an
entry in ~/.agents/.skill-lock.json or the project's skills-lock.json, or an *install.json file in its folder. Other
skills are yours. library.json in the data home corrects a wrong guess:

  {"mine": ["boxd-cli"], "installed": ["impeccable"]}

The STE check runs scripts/ste-lint.py of the asd-ste100 skill you have installed (or $TOKSCOPE_STE_LINT), so it
follows the same rules the agent does; tokscope ships no copy."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import paths
from ..core import skills
from ..core.markdown import frontmatter
from .changes import BENCH_PROJECT

HIDDEN = {"__pycache__", "node_modules"}
MAX_VIEW = 512_000
MAX_FILES = 400
LINT_TIMEOUT = 60
_lint_cache, _lint_lock = {}, threading.Lock()


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def _tilde(path):
    home = str(Path.home())
    s = str(path)
    return "~" + s[len(home):] if s == home or s.startswith(home + "/") else s


def _skipped(path):
    """Worktrees and benchmark copies repeat a real project's skills."""
    s = str(path)
    return "/.worktrees/" in s or s.startswith(str(paths.home() / "bench") + "/")


def roots(conn, project=None):
    """[(scope, skills folder)]: yours first, then each project's (the cwd of a session or a folder above it).
    `project` (a sessions.project value) keeps only the folders its sessions ran in; yours stay."""
    home = Path.home()
    found = [("personal", home / ".claude" / "skills")]
    try:
        cwds = [c for (c,) in conn.execute("SELECT DISTINCT cwd FROM sessions WHERE cwd IS NOT NULL AND cwd != ''"
                                           + " AND project = ?" * bool(project), (project,) if project else ())]
    except sqlite3.OperationalError:
        cwds = []
    seen = {found[0][1]}
    for cwd in cwds:
        for p in [Path(cwd), *Path(cwd).parents]:
            if p == home or p == p.parent:
                break
            folder = p / ".claude" / "skills"
            if folder not in seen and not _skipped(folder) and folder.is_dir():
                seen.add(folder)
                found.append((_tilde(p), folder))
    return found


def _origin(folder, name, lock_agents, lock_project, override):
    if name in override.get("mine", []):
        return "mine", "marked yours in library.json"
    if name in override.get("installed", []):
        return "installed", "marked installed in library.json"
    agents = Path.home() / ".agents"
    if folder.is_symlink() and agents in folder.resolve().parents:
        source = (lock_agents.get(name) or {}).get("source")
        return "installed", "linked from ~/.agents/skills" + (f", source {source}" if source else "")
    if name in lock_project:
        return "installed", f"in skills-lock.json, source {(lock_project[name] or {}).get('source', 'unknown')}"
    marker = next((p.name for p in folder.iterdir() if p.name.endswith("install.json")), None)
    if marker:
        return "installed", f"installer file {marker}"
    return "mine", ""


def files(folder):
    """[(relative path, bytes)] of a skill, SKILL.md first; hidden files and caches left out."""
    out = []
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if p.is_file() and not any(part.startswith(".") or part in HIDDEN for part in rel.parts) and p.suffix != ".pyc":
            out.append((rel.as_posix(), p.stat().st_size))
        if len(out) >= MAX_FILES:
            break
    return sorted(out, key=lambda f: (f[0] != "SKILL.md", f[0].count("/"), f[0]))


def discover(conn, project=None):
    """Every skill in the roots, as dicts: id, name, scope, folder, origin, reason, description, label."""
    override = _json(paths.home() / "library.json")
    lock_agents = _json(Path.home() / ".agents" / ".skill-lock.json").get("skills", {})
    out = []
    for scope, root in roots(conn, project):
        lock = _json(root.parent.parent / "skills-lock.json").get("skills", {}) if scope != "personal" else {}
        for folder in sorted(root.iterdir()) if root.is_dir() else []:
            skill_md = folder / "SKILL.md"
            if folder.name.startswith(".") or not skill_md.is_file():
                continue
            meta, _ = frontmatter(skill_md.read_text(errors="replace"))
            origin, reason = _origin(folder, folder.name, lock_agents, lock, override)
            out.append({"id": hashlib.sha1(str(folder).encode()).hexdigest()[:10], "name": meta.get("name") or folder.name,
                        "dir": folder.name, "scope": scope, "folder": folder, "origin": origin, "reason": reason,
                        "description": meta.get("description", ""), "label": meta.get("version")})
    return out


def read(skill, rel):
    """(text, None) for a text file of the skill, or (None, why not). Only a path files() lists can be read."""
    sizes = dict(files(skill["folder"]))
    if rel not in sizes:
        return None, "not a file of this skill"
    if sizes[rel] > MAX_VIEW:
        return None, f"too large to show ({sizes[rel]:,} bytes)"
    data = (skill["folder"] / rel).read_bytes()
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, f"a binary file ({len(data):,} bytes)"


def usage(conn, found, days=None, project=None, now=None):
    """{skill id: (loads, last load ts)} from the Skill calls of real sessions (bench ones left out, as versions() does),
    in the days and project given. A load counts for the skill folder Claude Code loaded it from in that session, so two
    skills of one name in different scopes keep their own counts; a name that matches no folder (a frontmatter name
    unlike its folder) falls back to the skill with that name."""
    where, params = ["s.project NOT LIKE ?"], [BENCH_PROJECT]
    if days:
        where.append("k.ts >= ?")
        since = (now or datetime.now(timezone.utc)) - timedelta(days=days)
        params.append(since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    if project:
        where.append("s.project = ?")
        params.append(project)
    try:
        rows = conn.execute("SELECT k.skill, s.cwd, count(*), max(k.ts) FROM skill_calls k JOIN sessions s USING (session_id) "
                            f"WHERE {' AND '.join(where)} GROUP BY 1, 2", params).fetchall()
    except sqlite3.OperationalError:
        return {}
    by_folder, by_name = {}, {}
    for k in found:
        by_folder.setdefault(k["folder"].resolve(), k)
        by_name.setdefault(k["name"], k)
        by_name.setdefault(k["dir"], k)
    out = {}
    for name, cwd, n, last in rows:
        folder = skills.skill_dir(name, cwd)
        k = by_folder.get(folder) if folder else None
        k = k or by_name.get(name)
        if k:
            n0, last0 = out.get(k["id"], (0, None))
            out[k["id"]] = (n0 + n, max(last0 or "", last or "") or None)
    return out


def ste_linter(found):
    """The ste-lint.py to run: $TOKSCOPE_STE_LINT, else the asd-ste100 skill's, else None."""
    if env := os.environ.get("TOKSCOPE_STE_LINT"):
        return Path(env) if Path(env).is_file() else None
    for k in found:
        if k["dir"] == "asd-ste100" and (k["folder"] / "scripts" / "ste-lint.py").is_file():
            return k["folder"] / "scripts" / "ste-lint.py"
    p = Path.home() / ".agents" / "skills" / "asd-ste100" / "scripts" / "ste-lint.py"
    return p if p.is_file() else None


def ste_lint(linter, files):
    """{file: [finding]} with one linter run for the files not checked since they last changed.
    A finding is the linter's JSON: line, col, rule, level ("advisory-free" is hard, "advisory" a hint), match, message."""
    key = lambda f: (str(f), f.stat().st_mtime_ns, str(linter))  # noqa: E731
    with _lint_lock:
        todo = [f for f in files if key(f) not in _lint_cache]
        if todo:
            # --baseline keeps exit 0 when there are findings; exit 2 is a usage error
            run = subprocess.run([sys.executable, "-I", str(linter), "--json", "--baseline", "1000000", *map(str, todo)],
                                 capture_output=True, text=True, timeout=LINT_TIMEOUT)
            if run.returncode != 0:
                raise RuntimeError((run.stderr or run.stdout).strip().splitlines()[-1] if (run.stderr or run.stdout).strip()
                                   else f"ste-lint exited {run.returncode}")
            found = {}
            for v in json.loads(run.stdout).get("violations", []):
                found.setdefault(v.get("file"), []).append(v)
            for f in todo:
                _lint_cache[key(f)] = found.get(str(f), [])
        return {f: _lint_cache[key(f)] for f in files}


def hard(findings):
    return sum(v.get("level") == "advisory-free" for v in findings)
