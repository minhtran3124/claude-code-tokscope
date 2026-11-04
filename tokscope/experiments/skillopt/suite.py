"""A skill's eval suite: load and check <skill>/evals/evals.json, split it into dev and holdout, draft cases from SKILL.md
and real transcript calls, approve a draft, and build an editor workspace that never holds holdout material."""
import hashlib
import json
import math
import os
import random
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ... import paths
from ...core import ingest, skills
from . import grade
from .sandbox import _name

NAME, DRAFT = "evals.json", "evals.draft.json"
TOUCH = ("Read", "Write", "Edit")


class Refused(ValueError):
    """The suite loads but fails its checks (the CLI exits 1); a plain ValueError is a load error (exit 2)."""


@dataclass
class Suite:
    folder: Path
    path: Path
    data: dict
    cases: list
    problems: list = field(default_factory=list)

    @property
    def refused(self):
        return bool(self.problems)


def _folder(skill, cwd):
    _name("skill", skill)
    if ":" in skill:
        raise ValueError(f"{skill}: a plugin skill cannot be evaluated yet; use a project or personal skill")
    folder = skills.skill_dir(skill, cwd=cwd or os.getcwd())
    if folder is None:
        raise ValueError(f"{skill}: no such skill folder")
    return folder


def suite_hash(data):
    """sha256 of the suite's cases and checks (canonical JSON), without the stored split."""
    body = {"evals": data.get("evals"), "checks": data.get("checks")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read(path, skill):
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
    return data


def _fixture_paths(folder, case):
    """(resolved paths, problems) of one case's `files`."""
    root, found, bad, seen = folder.resolve(), [], [], set()
    for rel in case.get("files") or []:
        src = (root / rel).resolve()
        if Path(rel).is_absolute() or not src.is_relative_to(root):
            bad.append(f"file {rel!r} is outside the skill folder")
        elif not src.exists():
            bad.append(f"file {rel!r} does not exist")
        elif src.name in seen:
            bad.append(f"two files named {src.name!r}")
        else:
            seen.add(src.name)
            found.append(src)
    return found, bad


def _overlap(a, b):
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _plan(data):
    """(dev ids, holdout ids, problems) from the stored split when its hash still matches, else from the seed."""
    h = suite_hash(data)
    ids = sorted(str(c.get("id")) for c in data.get("evals") or [])
    stored = data.get("split")
    if isinstance(stored, dict) and stored.get("hash") == h and isinstance(stored.get("holdout"), list):
        hold = [str(i) for i in stored["holdout"]]
        gone = [i for i in hold if i not in ids]
        problems = [f"split: holdout names {i!r}, which is not a case" for i in gone]
    else:
        order = list(ids)
        random.Random(int(h, 16)).shuffle(order)
        hold, problems = order[:math.ceil(len(ids) / 3)], []
    return [i for i in ids if i not in hold], sorted(hold), problems


def _problems(folder, data):
    out, seen, cases = [], set(), []
    shared = data.get("checks") or []
    for check in shared:
        try:
            grade.check_shape(check)
        except ValueError as e:
            out.append(f"suite checks: {e}")
    for n, case in enumerate(data.get("evals") or [], 1):
        if not isinstance(case, dict):
            out.append(f"case #{n}: must be an object")
            continue
        cases.append(case)
        cid = str(case.get("id")) if case.get("id") not in (None, "") else None
        tag = f"case {cid}" if cid else f"case #{n}"
        if cid is None:
            out.append(f"{tag}: no id")
        elif cid in seen:
            out.append(f"{tag}: duplicate id")
        seen.add(cid)
        if not case.get("prompt"):
            out.append(f"{tag}: no prompt")
        own = case.get("checks")
        if own is not None and not isinstance(own, list):
            out.append(f"{tag}: 'checks' must be a list")
            own = []
        if case.get("files") is not None and not (isinstance(case["files"], list)
                                                  and all(isinstance(r, str) for r in case["files"])):
            out.append(f"{tag}: 'files' must be a list of paths")
            case = {**case, "files": []}
        if not own and not shared:
            out.append(f"{tag}: no machine checks")
        for check in own or []:
            try:
                grade.check_shape(check)
            except ValueError as e:
                out.append(f"{tag}: {e}")
        out += [f"{tag}: {m}" for m in _fixture_paths(folder, case)[1]]
    return out, cases


def load(skill, cwd=None, name=NAME):
    """Suite with every problem found, not only the first. ValueError (a load error) for a missing folder or file or
    unreadable JSON."""
    folder = _folder(skill, cwd)
    path = folder / "evals" / name
    data = _read(path, skill)
    problems, cases = _problems(folder, data)
    if not problems and len(cases) >= 2:
        dev, hold, bad = _plan(data)
        problems += bad
        if not bad:
            problems += _leaks(folder, cases, hold)
    return Suite(folder, path, data, cases, problems)


def _leaks(folder, cases, hold):
    by_id = {str(c["id"]): c for c in cases}
    files = {s for s in skills._files(folder)}
    held, dev, out = [], [], []
    for cid, case in by_id.items():
        (held if cid in hold else dev).append((cid, _fixture_paths(folder, case)[0]))
    for cid, srcs in held:
        for src in srcs:
            if any(f == src or f.is_relative_to(src) for f in (p.resolve() for p in files)):
                out.append(f"case {cid}: holdout fixture {src.name!r} is part of the skill files")
            for did, dsrcs in dev:
                if any(_overlap(src, d) for d in dsrcs):
                    out.append(f"case {did}: fixture shared with holdout case {cid}")
    return out


def _atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".evals-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def split(suite, write=True):
    """(dev ids, holdout ids). The split is written into evals.json once; a stored split whose hash still matches the
    suite is kept as it is (a hand-chosen holdout survives); any edit to a case or check re-splits."""
    if suite.problems:
        raise Refused("suite has problems: " + "; ".join(suite.problems))
    if len(suite.cases) < 2:
        raise Refused("needs at least 2 cases to split")
    dev, hold, _ = _plan(suite.data)
    h = suite_hash(suite.data)
    stored = suite.data.get("split")
    if write and not (isinstance(stored, dict) and stored.get("hash") == h):
        suite.data["split"] = {"hash": h, "holdout": hold}
        _atomic_write(suite.path, suite.data)
    return dev, hold


def editor_workspace(skill, dest, cwd=None):
    """Copy the skill's fingerprint file set and only the dev cases (with the fixtures only they name) to `dest`. The
    folder the editor sees never holds a holdout id, prompt or fixture. `dest` must not exist or be empty."""
    suite = load(skill, cwd)
    dev, _ = split(suite, write=False)
    dest = Path(dest)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError(f"{dest} must not exist or be empty")
    for f in skills._files(suite.folder):
        target = dest / f.relative_to(suite.folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    keep = [c for c in suite.cases if str(c["id"]) in dev]
    root = suite.folder.resolve()
    for case in keep:
        for src in _fixture_paths(suite.folder, case)[0]:
            target = dest / src.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, target, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
    out = {k: v for k, v in suite.data.items() if k not in ("split", "evals")}
    out["evals"] = keep
    (dest / "evals").mkdir(exist_ok=True)
    (dest / "evals" / NAME).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return dest


def _touched(session_id, prompt_idx, projects_dir):
    """(file paths the Read/Write/Edit calls of one prompt named, the session's working folder or None), from the
    session transcript."""
    found = ingest.find_transcripts(session_id, projects_dir)
    if not found:
        return [], None
    idx, out, root = 0, [], None
    for line in found[0].read_text(errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if root is None and isinstance(rec.get("cwd"), str):
            root = rec["cwd"]
        if rec.get("type") == "user" and ingest._is_human_prompt(rec):
            m = ingest.COMMAND_RE.search(ingest._text((rec.get("message") or {}).get("content")))
            if not (m and m.group(1) in ingest.BUILTIN_COMMANDS):
                idx += 1
        elif rec.get("type") == "assistant" and idx == prompt_idx:
            content = (rec.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                fp = (b.get("input") or {}).get("file_path") if isinstance(b, dict) and b.get("name") in TOUCH else None
                if isinstance(fp, str) and fp not in out:
                    out.append(fp)
    return out, root


_SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".docker", ".config", ".netrc", ".git", ".azure", ".gcloud"}
_SECRET_NAME = re.compile(
    r"^(\.env.*|\.netrc|\.npmrc|\.pypirc|id_(rsa|dsa|ecdsa|ed25519).*|credentials.*|secrets?(\..*)?|.*\.(pem|key|p12|pfx|keystore|kdbx))$",
    re.I)


def _secret(path, root=None):
    """True for a path that looks like a credential or sits in a credentials folder; draft() never copies those.
    Only the folders below `root` (the session's working folder) are checked when the file is inside it, so a project
    under .config is fine. With no root, or a file outside it, every folder of the path counts."""
    path = Path(path)
    parts = path.parts
    if root:
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            pass
    return bool(_SECRET_NAME.match(path.name)) or any(part in _SECRET_DIRS for part in parts)


def _description(folder):
    text = (folder / "SKILL.md").read_text(errors="replace")
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    return m.group(1).strip().strip("\"'") if m else folder.name


def draft(skill, n=5, cwd=None, projects_dir=None):
    """Write evals/evals.draft.json with up to `n` cases from the skill's real calls (their prompt text and the files
    they touched). evals.json is never touched. Returns {"path", "cases", "skipped", "note"}. No LLM."""
    folder = _folder(skill, cwd)
    conn = ingest.connect(paths.db())
    try:
        rows = conn.execute(
            "SELECT c.session_id, c.prompt_idx, p.text FROM skill_calls c LEFT JOIN prompts p "
            "ON p.session_id = c.session_id AND p.prompt_idx = c.prompt_idx "
            "WHERE c.skill = ? AND COALESCE(c.failed, 0) = 0 AND c.prompt_idx IS NOT NULL "
            "ORDER BY c.ts DESC", (skill,)).fetchall()
    finally:
        conn.close()
    cases, skipped, seen = [], 0, set()
    for sid, pidx, text in rows:
        if (sid, pidx) in seen:
            continue
        seen.add((sid, pidx))
        if not (text or "").strip():
            skipped += 1
            continue
        if len(cases) >= n:
            break
        cid = f"{sid[:8]}-{pidx}"
        files = []
        touched, root = _touched(sid, pidx, projects_dir)
        for raw in touched:
            src = Path(raw)
            real_root = Path(root).resolve() if root else None
            if not src.is_absolute() or _secret(src, root) or _secret(src.resolve(), real_root):
                continue
            if not src.is_file() or src.resolve().is_relative_to(folder.resolve()):
                continue
            rel = Path("evals") / "fixtures" / cid / src.name
            if (folder / rel).exists() and (folder / rel).read_bytes() != src.read_bytes() or rel.as_posix() in files:
                continue
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, folder / rel)
            files.append(rel.as_posix())
        case = {"id": cid, "prompt": text.strip()}
        if files:
            case["files"] = files
        cases.append(case)
    note = f"{len(cases)} cases from real calls" + (f"; {skipped} skipped for no prompt text" if skipped else "")
    if not cases:
        cases = [{"id": "from-description", "prompt": f"Use the {skill} skill: {_description(folder)}"}]
        note = "no usable calls: one case from the SKILL.md description" + (f"; {skipped} skipped for no prompt text" if skipped else "")
    path = folder / "evals" / DRAFT
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, {"evals": cases, "checks": []})
    return {"path": path, "cases": cases, "skipped": skipped, "note": note}


def approve(skill, cwd=None, force=False):
    """Copy the draft to evals.json when it passes the checks. Refused (nothing written) when it does not, or when
    evals.json already exists and force is false (it may hold hand-curated cases and the holdout split). The draft
    stays."""
    folder = _folder(skill, cwd)
    if (folder / "evals" / NAME).exists() and not force:
        raise Refused(f"{folder / 'evals' / NAME} already exists; pass --force to overwrite it")
    suite = load(skill, cwd, DRAFT)
    if suite.problems:
        raise Refused("draft has problems: " + "; ".join(suite.problems))
    data = {k: v for k, v in suite.data.items() if k != "split"}
    _atomic_write(folder / "evals" / NAME, data)
    return folder / "evals" / NAME
