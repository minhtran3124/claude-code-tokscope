"""Skill versions: a content fingerprint of each skill's folder, so tokscope sees when a skill changed.

A version is the SHA-256 of the skill's folder (relative paths and bytes), so the same content has the same
version on any machine, and a touch or checkout that changes nothing is no change. Only what the skill can put in
front of the model counts: hidden files, caches, eval/test folders and files over 1 MB are left out, so an eval run
writing results into the folder is not a new version. A skill built into Claude Code has no folder on disk; its
version is the Claude Code version (cc-2.1.304).
Versions are recorded two ways:
- at load: the mod marks each Skill call, and `tokscope mark` hashes the folder that call loaded (exact);
- at ingest: every skill seen in a transcript is hashed again; a new hash is a change.
A version is dated by the best evidence of when it was in use: the earliest load whose SKILL.md text (kept in the
transcript's request blob) matches it, else its git commit when the folder is clean, else its files' mtime. A load
whose kept text differs from a version is not counted for that version.
A load takes the version marked for its tool call, else the newest version first seen before it, else none
(the load happened before tokscope saw the skill). Each version's files are kept under data/skills/ for diffs."""

import hashlib
import json
import re
import shutil
import subprocess
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_versions (
    skill TEXT, version TEXT, path TEXT, label TEXT, first_seen TEXT, last_seen TEXT, source TEXT, body_hash TEXT,
    PRIMARY KEY (skill, version)
);
CREATE TABLE IF NOT EXISTS skill_load_versions (
    session_id TEXT, tool_use_id TEXT, skill TEXT, version TEXT, ts TEXT, PRIMARY KEY (session_id, tool_use_id)
);
"""
TOKENS = "(input + cache_read + cache_write_5m + cache_write_1h + output)"
FRONTMATTER_VERSION = re.compile(r"^version:\s*['\"]?([^'\"\s]+)", re.MULTILINE)


SKIP_DIRS = {"__pycache__", "node_modules", "eval", "evals", "tests", "test", "fixtures", "results"}
MAX_BYTES = 1_000_000
BUNDLED_ROOT = Path("/tmp")  # Claude Code unpacks its built-in skills' files under /tmp/claude-<uid>/bundled-skills


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _body(skill_md):
    """SKILL.md as Claude Code puts it in the context: the frontmatter dropped."""
    if skill_md.startswith("---") and skill_md.count("---") >= 2:
        skill_md = skill_md.split("---", 2)[2]
    return skill_md.strip()


def body_hash(folder):
    return _sha(_body((Path(folder) / "SKILL.md").read_text(errors="replace")))


def loaded_text_hash(text, args=None):
    """The hashes a load's kept SKILL.md may match, space-separated: 'Base directory for this skill: …', the body,
    then any ARGUMENTS. Claude Code puts a call's arguments after the body, or where the body says $ARGUMENTS.
    The second hash puts the placeholder back; the first keeps the text as is, since an argument like "update"
    may also be an ordinary word of the skill."""
    body = text.split("\n\n", 1)[1] if "\n\n" in text else ""
    body = body.split("\n\n\nARGUMENTS: ", 1)[0].strip()
    hashes = [_sha(body)]
    if args and args.strip() and args.strip() in body:
        hashes.append(_sha(body.replace(args.strip(), "$ARGUMENTS")))
    return " ".join(dict.fromkeys(hashes))


def _ensure(conn):
    conn.executescript(SCHEMA)
    if "body_hash" not in {c[1] for c in conn.execute("PRAGMA table_info(skill_versions)")}:
        conn.execute("ALTER TABLE skill_versions ADD COLUMN body_hash TEXT")


def _skipped(rel):
    return any(part.startswith(".") or part in SKIP_DIRS or part.endswith(".pyc") for part in rel.parts)


def _files(folder):
    return sorted(p for p in folder.rglob("*")
                  if p.is_file() and not _skipped(p.relative_to(folder)) and p.stat().st_size <= MAX_BYTES)


def fingerprint(folder):
    """12 hex chars of SHA-256 over every file's relative path and bytes; None when there is no SKILL.md."""
    folder = Path(folder)
    if not (folder / "SKILL.md").is_file():
        return None
    h = hashlib.sha256()
    for f in _files(folder):
        h.update(f.relative_to(folder).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def label(folder):
    """The human version in SKILL.md frontmatter (`version: 1.3.0`), if the author keeps one."""
    text = (Path(folder) / "SKILL.md").read_text(errors="replace")
    head = text.split("---", 2)[1] if text.startswith("---") and text.count("---") >= 2 else ""
    m = FRONTMATTER_VERSION.search(head)
    return m.group(1) if m else None


def _plugin_skill(plugin, skill, cwd):
    """plugin:skill -> its folder in the installed plugin; a project install under cwd wins over a user one."""
    try:
        installed = json.loads((Path.home() / ".claude" / "plugins" / "installed_plugins.json").read_text())
    except (OSError, ValueError):
        return None
    entries = [e for key, es in installed.get("plugins", {}).items() if key.split("@")[0] == plugin for e in es]
    entries.sort(key=lambda e: not (e.get("scope") == "project" and cwd and str(cwd).startswith(e.get("projectPath", "\0"))))
    for e in entries:
        folder = Path(e.get("installPath", "")) / "skills" / skill
        if (folder / "SKILL.md").is_file():
            return folder
    return None


def _installed_skill(skill):
    """A plugin skill called without its plugin prefix: the one installed plugin that has it."""
    try:
        installed = json.loads((Path.home() / ".claude" / "plugins" / "installed_plugins.json").read_text())
    except (OSError, ValueError):
        return None
    found = {Path(e.get("installPath", "")) / "skills" / skill for es in installed.get("plugins", {}).values() for e in es}
    found = [f for f in found if (f / "SKILL.md").is_file()]
    return found[0] if len({fingerprint(f) for f in found}) == 1 else None


def _installed_plugin_of(skill):
    try:
        installed = json.loads((Path.home() / ".claude" / "plugins" / "installed_plugins.json").read_text())
    except (OSError, ValueError):
        return None
    owners = {key.split("@")[0] for key, es in installed.get("plugins", {}).items()
              for e in es if (Path(e.get("installPath", "")) / "skills" / skill / "SKILL.md").is_file()}
    return owners.pop() if len(owners) == 1 else None


@lru_cache(maxsize=None)
def canonical_name(name, cwd=None):
    """plugin:skill for a plugin skill called by its bare name, so one skill is one row; other names as they are."""
    if not name or ":" in name:
        return name
    local = [p / ".claude" / "skills" / name for p in ([Path(cwd), *Path(cwd).parents] if cwd else [])]
    local.append(Path.home() / ".claude" / "skills" / name)
    if any((f / "SKILL.md").is_file() for f in local):
        return name
    plugin = _installed_plugin_of(name)
    return f"{plugin}:{name}" if plugin else name


def builtin_version(name):
    """cc-<version> for a skill built into Claude Code (unpacked under /tmp/claude-*/bundled-skills/<version>/)."""
    hits = sorted(BUNDLED_ROOT.glob(f"claude-*/bundled-skills/*/*/{name}"), key=lambda p: p.stat().st_mtime)
    return f"cc-{hits[-1].parent.parent.name}" if hits else None


def skill_dir(name, cwd=None):
    """The folder Claude Code loads `name` from: a plugin's, the project's (cwd or a parent), the user's, or built in."""
    if ":" in name:
        return _plugin_skill(*name.split(":", 1), cwd)
    candidates = [p / ".claude" / "skills" / name for p in ([Path(cwd), *Path(cwd).parents] if cwd else [])]
    candidates.append(Path.home() / ".claude" / "skills" / name)
    for folder in candidates:
        if (folder / "SKILL.md").is_file():
            return folder.resolve()
    return _installed_skill(name)


def _snapshot(skill, version, folder):
    dest = paths.home() / "data" / "skills" / skill.replace(":", "__") / version
    for f in [] if dest.exists() else _files(folder):  # the same files the fingerprint covers
        target = dest / f.relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def record(conn, skill, folder, seen_at, source, version=None):
    """Store the version the folder holds now; returns it. A version already known only moves its last_seen."""
    version = version or (fingerprint(folder) if folder else None)
    if version is None:
        return None
    _ensure(conn)
    known = conn.execute("SELECT 1 FROM skill_versions WHERE skill = ? AND version = ?", (skill, version)).fetchone()
    if known:
        conn.execute("UPDATE skill_versions SET last_seen = max(last_seen, ?) WHERE skill = ? AND version = ?",
                     (seen_at, skill, version))
        if source == "load":  # a load is proof the version existed then; a scan's date is only an estimate
            conn.execute("UPDATE skill_versions SET first_seen = min(first_seen, ?) WHERE skill = ? AND version = ?",
                         (seen_at, skill, version))
    else:
        conn.execute("INSERT INTO skill_versions VALUES (?,?,?,?,?,?,?,?)",
                     (skill, version, str(folder) if folder else None, label(folder) if folder else None, seen_at, seen_at,
                      source, body_hash(folder) if folder else None))
        if folder:
            _snapshot(skill, version, folder)
    return version


def record_load(conn, session_id, tool_use_id, skill, cwd, ts):
    """The exact version one Skill call loaded, hashed while the call is still fresh (the mod's mark)."""
    folder = skill_dir(skill, cwd)
    version = record(conn, skill, folder, ts, "load", None if folder else builtin_version(skill))
    if version and tool_use_id:
        conn.execute("INSERT OR REPLACE INTO skill_load_versions VALUES (?,?,?,?,?)", (session_id, tool_use_id, skill, version, ts))
    return version


def _git_date(folder):
    """The last commit that touched the folder, when git tracks it and it has no uncommitted edits."""
    def git(*args):
        out = subprocess.run(["git", "-C", str(folder), *args, "--", "."], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    try:
        if not git("ls-files") or git("status", "--porcelain") != "":
            return None
        return git("log", "-1", "--format=%cI") or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()


def _evidence(conn, skill, folder):
    """The earliest moment this content is known to exist: a matching kept load, the git commit, the files' mtime."""
    dates = [_iso(max(f.stat().st_mtime for f in _files(folder)))]
    git = _git_date(folder)
    if git:
        dates.append(_utc(git))
    seen = conn.execute("SELECT min(ts) FROM skill_calls WHERE skill = ? AND ' ' || text_hash || ' ' LIKE ?",
                        (skill, f"% {body_hash(folder)} %")).fetchone()[0]
    if seen:
        dates.append(_utc(seen))
    return min(dates)


def scan(conn, now=None):
    """Hash every skill a transcript has loaded, in the folder its latest session would load it from, and date it."""
    _ensure(conn)
    now = now or datetime.now(timezone.utc).isoformat()
    for skill, cwd in conn.execute(
            "SELECT k.skill, s.cwd FROM skill_calls k JOIN sessions s USING (session_id) "
            "WHERE k.ts = (SELECT max(ts) FROM skill_calls WHERE skill = k.skill) GROUP BY k.skill").fetchall():
        folder = skill_dir(skill, cwd)
        version = fingerprint(folder) if folder else builtin_version(skill)
        if version is None:
            continue
        row = conn.execute("SELECT first_seen, source FROM skill_versions WHERE skill = ? AND version = ?", (skill, version)).fetchone()
        # a version never starts before the one it replaced
        floor = conn.execute("SELECT max(first_seen) FROM skill_versions WHERE skill = ? AND version != ? AND first_seen < ?",
                             (skill, version, row[0] if row else "9")).fetchone()[0]
        dated = _evidence(conn, skill, folder) if folder else now
        dated = dated if not floor or dated > floor else now if not row else row[0]
        if row:
            conn.execute("UPDATE skill_versions SET last_seen = ?, first_seen = min(first_seen, ?) WHERE skill = ? AND version = ?",
                         (now, dated, skill, version))
        else:
            record(conn, skill, folder, dated, "scan", version)
    conn.commit()


def load_versions(conn):
    """Every skill load with its version: (session_id, prompt_idx, skill, ts, version or None, exact)."""
    _ensure(conn)
    timeline, body, by_text = {}, {}, {}
    for skill, version, first, bh, source in conn.execute(
            "SELECT skill, version, first_seen, body_hash, source FROM skill_versions ORDER BY first_seen"):
        body[(skill, version)] = bh
        if bh:
            by_text.setdefault((skill, bh), version)
        # a version rebuilt from a transcript is known only at the loads that kept its text, not over a span of time
        if source != "transcript":
            timeline.setdefault(skill, []).append((first, version))
    out = []
    for sid, i, skill, ts, text, exact in conn.execute(
            "SELECT k.session_id, k.prompt_idx, k.skill, k.ts, k.text_hash, v.version FROM skill_calls k "
            "LEFT JOIN skill_load_versions v ON v.session_id = k.session_id AND v.tool_use_id = k.tool_use_id"):
        version = exact
        if version is None and text:
            # the transcript kept the text this load read: the version with that text is it, whatever the dates say
            version = next((by_text[(skill, h)] for h in text.split() if (skill, h) in by_text), None)
            if version is None:
                before = [v for first, v in timeline.get(skill, []) if first <= _utc(ts or "1970-01-01T00:00:00Z")]
                version = before[-1] if before and body.get((skill, before[-1])) is None else None
        elif version is None:
            before = [v for first, v in timeline.get(skill, []) if first <= _utc(ts or "1970-01-01T00:00:00Z")]
            version = before[-1] if before else None
        out.append((sid, i, skill, ts, version, exact is not None))
    return out


def versions(conn, skill=None, bench_project="%tokscope%-bench-%"):
    """Per skill and version: label, first seen, loads, and median tokens per load (one prompt's requests)."""
    # one unit per prompt and skill; a prompt that loaded the skill twice counts the version of its last load
    units = {(sid, i, sk): (version, exact) for sid, i, sk, _, version, exact in sorted(load_versions(conn), key=lambda r: r[3] or "")}
    tokens = {(sid, i, sk): t for sid, i, sk, t in conn.execute(
        f"SELECT r.session_id, r.prompt_idx, r.skill, sum({TOKENS}) FROM requests r JOIN sessions s USING (session_id) "
        f"WHERE r.skill IS NOT NULL AND s.project NOT LIKE ? GROUP BY 1, 2, 3", (bench_project,))}
    per = {}
    for key, (version, exact) in units.items():
        if key in tokens:
            per.setdefault((key[2], version), []).append((tokens[key], exact))
    rows = []
    for sk, version, lbl, first, source in conn.execute(
            "SELECT skill, version, label, first_seen, source FROM skill_versions ORDER BY skill, first_seen"):
        if skill and sk != skill:
            continue
        us = per.get((sk, version), [])
        rows.append({"skill": sk, "version": version, "label": lbl, "first_seen": first, "source": source,
                     "loads": len(us), "exact": sum(e for _, e in us), "tokens_median": median(t for t, _ in us) if us else None})
    for (sk, version), us in sorted(per.items(), key=lambda kv: kv[0][0]):
        if version is None and (not skill or sk == skill):
            rows.append({"skill": sk, "version": None, "label": None, "first_seen": None, "source": "before tracking",
                         "loads": len(us), "exact": 0, "tokens_median": median(t for t, _ in us)})
    # per skill, oldest first; loads from before tracking lead
    return sorted(rows, key=lambda r: (r["skill"], r["first_seen"] or ""))


def snapshot_dir(skill, version):
    return paths.home() / "data" / "skills" / skill.replace(":", "__") / version


def diff(skill, old, new, max_lines=300):
    """Unified diff of two kept versions, file by file; None when either version's files were not kept."""
    import difflib

    a, b = snapshot_dir(skill, old), snapshot_dir(skill, new)
    if not (a.is_dir() and b.is_dir()):
        return None
    names = sorted({p.relative_to(a).as_posix() for p in _files(a)} | {p.relative_to(b).as_posix() for p in _files(b)})
    out = []
    for name in names:
        before, after = a / name, b / name
        try:
            old_lines = before.read_text().splitlines() if before.exists() else []
            new_lines = after.read_text().splitlines() if after.exists() else []
        except UnicodeDecodeError:
            out.append(f"Binary file {name} differs")
            continue
        out += list(difflib.unified_diff(old_lines, new_lines, f"{old}/{name}", f"{new}/{name}", lineterm="", n=2))
    if len(out) > max_lines:
        out = out[:max_lines] + [f"… {len(out) - max_lines} more lines"]
    return out


def kept_versions(skill):
    """Versions whose files were kept, oldest first by when they were kept."""
    root = paths.home() / "data" / "skills" / skill.replace(":", "__")
    return [p.name for p in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime)] if root.is_dir() else []


def resolve_version(skill, ref):
    """A kept version from a hash prefix ('790ed4'); ValueError names the kept ones when none or several match."""
    kept = kept_versions(skill)
    hits = [v for v in kept if v.startswith(ref)]
    if len(hits) != 1:
        found = ", ".join(kept) or "none"
        raise ValueError(f"{skill}: {'no' if not hits else 'more than one'} kept version matches {ref!r} (kept: {found})")
    return hits[0]


def check_pinnable(skill):
    """ValueError when a pinned project copy of the skill would not be the one a session loads."""
    if ":" in skill:
        raise ValueError(f"{skill}: a plugin skill cannot be pinned yet; pin a project skill")
    # personal skills win over project ones (code.claude.com/docs/en/skills), so a pinned project copy would be ignored
    personal = Path.home() / ".claude" / "skills" / skill
    if (personal / "SKILL.md").exists():
        raise ValueError(f"{skill}: {personal} wins over a pinned project copy; move it aside to benchmark this skill")


def pin(skill, version, root):
    """Put one kept version of a project skill at <root>/.claude/skills/<skill>, where a session in root
    loads it from. Replaces what was there without writing through hard links into a shared snapshot."""
    check_pinnable(skill)
    dest = Path(root) / ".claude" / "skills" / skill
    if dest.exists() or dest.is_symlink():
        shutil.rmtree(dest) if dest.is_dir() and not dest.is_symlink() else dest.unlink()
    shutil.copytree(snapshot_dir(skill, version), dest)
    return dest


def check_load(conn, session_id, skill, version):
    """Did this session load the pinned version? 'ok', 'other text' (another copy of the skill won, e.g. a personal
    one), 'not loaded' (the model never called it), or 'unconfirmed' (Claude Code kept no text to compare)."""
    texts = [t for (t,) in conn.execute("SELECT text_hash FROM skill_calls WHERE session_id = ? AND skill = ?", (session_id, skill))]
    if not texts:
        return "not loaded"
    want = _sha(_body((snapshot_dir(skill, version) / "SKILL.md").read_text(errors="replace")))
    kept = [t for t in texts if t]
    if not kept:
        return "unconfirmed"
    return "ok" if all(want in t.split() for t in kept) else "other text"


def _kept_body(text, args):
    """The SKILL.md body a load kept, with $ARGUMENTS put back only where the arguments went inline."""
    body = text.split("\n\n", 1)[1] if "\n\n" in text else ""
    if "\n\n\nARGUMENTS: " in body:  # appended after the body: the body is the file's own text
        return body.split("\n\n\nARGUMENTS: ", 1)[0].strip()
    return (body.replace(args.strip(), "$ARGUMENTS") if args and args.strip() else body).strip()


def _transcripts(projects_dir, project, session_id):
    main = Path(projects_dir) / project / f"{session_id}.jsonl"
    subs = main.with_suffix("") / "subagents"
    return [main, *sorted(subs.glob("agent-*.jsonl"))] if main.exists() else []


def _kept_texts(paths_, tool_use_ids):
    """tool_use_id -> (kept skill text, call args) for the given Skill calls, read from their transcripts."""
    found, args = {}, {}
    for path in paths_:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"name":"Skill"' in line or '"name": "Skill"' in line:
                    try:
                        for b in (json.loads(line).get("message") or {}).get("content") or []:
                            if isinstance(b, dict) and b.get("id") in tool_use_ids:
                                args[b["id"]] = (b.get("input") or {}).get("args")
                    except json.JSONDecodeError:
                        pass
                if '"api-request-blob"' not in line[:40] or "Base directory for this skill:" not in line:
                    continue
                try:
                    content = (json.loads(line).get("message") or {}).get("content") or []
                except json.JSONDecodeError:
                    continue
                for prev, block in zip(content, content[1:]):
                    if isinstance(prev, dict) and prev.get("tool_use_id") in tool_use_ids and isinstance(block, dict) \
                            and block.get("text", "").startswith("Base directory for this skill:"):
                        found[prev["tool_use_id"]] = block["text"]
    return {tid: (text, args.get(tid)) for tid, text in found.items()}


def _kept_command_texts(paths_, timestamps):
    """timestamp -> (kept skill text, command args) for typed /skill loads: the meta message after the command."""
    from .ingest import COMMAND_ARGS_RE, SKILL_TEXT, _text

    found, pending = {}, None
    for path in paths_:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"type":"user"' not in line and '"type": "user"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = _text((rec.get("message") or {}).get("content"))
                if rec.get("timestamp") in timestamps and "<command-name>" in text:
                    m = COMMAND_ARGS_RE.search(text)
                    pending = (rec["timestamp"], m.group(1) if m else None)
                elif pending and rec.get("isMeta") and text.startswith(SKILL_TEXT):
                    found[pending[0]] = (text, pending[1])
                    pending = None
    return found


def import_from_transcripts(conn, projects_dir, skill=None):
    """Keep the older versions a transcript still shows: a load whose kept SKILL.md matches no known version becomes
    a version of its own, dated by its first load. Only SKILL.md was kept, so its other files come from the oldest
    version kept on disk and its frontmatter from that version's SKILL.md (the model reads neither when called by
    name). Returns [(skill, version, first load, loads)]."""
    _ensure(conn)
    known = {(s, b) for s, b in conn.execute("SELECT skill, body_hash FROM skill_versions WHERE body_hash IS NOT NULL")}
    rows = conn.execute(
        "SELECT k.skill, k.session_id, s.project, k.tool_use_id, k.text_hash, k.ts FROM skill_calls k JOIN sessions s "
        "USING (session_id) WHERE k.text_hash IS NOT NULL" + (" AND k.skill = ?" if skill else ""),
        (skill,) if skill else ()).fetchall()
    todo = {}
    for sk, sid, project, tid, text_hash, ts in rows:
        if not any((sk, h) in known for h in text_hash.split()) and kept_versions(sk):
            todo.setdefault((sid, project), []).append((sk, tid, ts))
    bodies = {}  # (skill, body hash) -> [body, first ts, loads]
    for (sid, project), loads in todo.items():
        files = _transcripts(projects_dir, project, sid)
        texts = _kept_texts(files, {tid for _, tid, _ in loads if tid})
        typed = _kept_command_texts(files, {ts for _, tid, ts in loads if not tid})
        for sk, tid, ts in loads:
            kept = texts.get(tid) if tid else typed.get(ts)
            if kept:
                body = _kept_body(*kept)
                entry = bodies.setdefault((sk, _sha(body)), [body, ts, 0])
                entry[1], entry[2] = min(entry[1], ts), entry[2] + 1
    imported = []
    for (sk, bh), (body, first, n) in sorted(bodies.items(), key=lambda kv: kv[1][1]):
        base = snapshot_dir(sk, kept_versions(sk)[0])
        head = (base / "SKILL.md").read_text(errors="replace")
        rest = head.split("---", 2)[2] if head.startswith("---") and head.count("---") >= 2 else None
        # the frontmatter and the whitespace that followed it, so the rebuilt file differs from it only in the body
        front = head[:len(head) - len(rest.lstrip())] if rest is not None else ""
        work = paths.home() / "data" / "skills-import" / sk.replace(":", "__") / bh
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(base, work)
        (work / "SKILL.md").write_text(f"{front}{body}\n")
        if body_hash(work) != bh:  # the rebuilt file must read back as the text the model saw
            continue
        version = record(conn, sk, work, _utc(first), "transcript")
        conn.execute("UPDATE skill_versions SET path = NULL WHERE skill = ? AND version = ?", (sk, version))
        shutil.rmtree(work)
        imported.append((sk, version, first, n))
    conn.commit()
    return imported


def turn_versions(conn, session_id=None):
    """(session_id, prompt_idx, skill) -> (version, exact) for each prompt that loaded a skill; the last load of a
    skill in a prompt wins. One source for the report's turn rows, the pane and `tokscope session`."""
    out = {}
    for sid, i, skill, ts, version, exact in sorted(load_versions(conn), key=lambda r: r[3] or ""):
        if version and (session_id is None or sid == session_id):
            out[(sid, i, skill)] = (version, exact)
    return out


def session_skill_versions(conn, session_id):
    """skill -> the version its last load in this session used."""
    return {skill: v for (_, _, skill), (v, _) in sorted(turn_versions(conn, session_id).items(), key=lambda kv: kv[0][1] or 0)}
