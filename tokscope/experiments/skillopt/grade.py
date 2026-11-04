"""Machine grading of one eval case: checks over the stream-json events and the sandbox files. No LLM."""
import json
import re
from pathlib import Path

REQUIRED = {
    "answer_regex": ("pattern",),
    "file_exists": ("path",),
    "file_contains": ("path", "pattern"),
    "tool_called": ("tool",),
    "tool_order": ("tools",),
    "no_permission_denials": (),
}


def parse(lines):
    """stream-json lines -> events; lines that are not JSON objects are skipped."""
    events = []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events


def check_shape(check):
    """ValueError for an unknown check type or a missing key; never a silent pass."""
    if not isinstance(check, dict):
        raise ValueError(f"check must be an object, got {check!r}")
    kind = check.get("type")
    if kind not in REQUIRED:
        raise ValueError(f"unknown check type {kind!r} (known: {', '.join(REQUIRED)})")
    for key in REQUIRED[kind]:
        if not check.get(key):
            raise ValueError(f"{kind} check needs {key!r}")
    if kind in ("answer_regex", "file_contains"):
        try:
            re.compile(check["pattern"])
        except re.error as e:
            raise ValueError(f"{kind}: bad pattern {check['pattern']!r}: {e}") from None
    if kind == "tool_order" and not isinstance(check["tools"], list):
        raise ValueError("tool_order 'tools' must be a list")
    return check


def tool_calls(events):
    """(name, input) of every assistant tool_use block, in stream order."""
    calls = []
    for ev in events:
        if ev.get("type") != "assistant":
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append((block.get("name", ""), block.get("input") or {}))
    return calls


def denials(events):
    """Denied tool calls: system/permission_denied events plus the result's permission_denials[]."""
    found = []
    for ev in events:
        if ev.get("type") == "system" and ev.get("subtype") == "permission_denied":
            found.append(ev.get("tool_name") or ev.get("message") or "denied")
        elif ev.get("type") == "result":
            for d in ev.get("permission_denials") or []:
                found.append(d.get("tool_name", "denied") if isinstance(d, dict) else str(d))
    return found


def _result(events):
    return next((ev for ev in reversed(events) if ev.get("type") == "result"), None)


def _inside(sandbox, rel):
    """The path inside the sandbox, or None when it is absolute or escapes it."""
    root = Path(sandbox).resolve()
    target = (root / rel).resolve()
    return target if not Path(rel).is_absolute() and target.is_relative_to(root) else None


def _clip(text, n=200):
    text = str(text)
    return text if len(text) <= n else text[:n] + "..."


def _grade_one(check, events, sandbox, answer):
    kind = check["type"]
    if kind == "answer_regex":
        m = re.search(check["pattern"], answer, re.M)
        if not m:
            return False, f"no match for /{check['pattern']}/ in: {_clip(answer) or '(empty answer)'}"
        a, b = max(0, m.start() - 80), min(len(answer), m.end() + 80)
        return True, f"matched {m.group(0)!r} in: ...{answer[a:b]}..."
    if kind in ("file_exists", "file_contains"):
        target = _inside(sandbox, check["path"])
        if target is None:
            return False, f"{check['path']}: path leaves the sandbox"
        if not target.is_file():
            return False, f"{check['path']}: missing"
        if kind == "file_exists":
            return True, f"{check['path']}: exists ({target.stat().st_size} bytes)"
        text = target.read_text(errors="replace")
        m = re.search(check["pattern"], text, re.M)
        if not m:
            return False, f"{check['path']}: no match for /{check['pattern']}/ in: {_clip(text) or '(empty file)'}"
        line = text[text.rfind("\n", 0, m.start()) + 1:].split("\n", 1)[0]
        return True, f"{check['path']}: matched line {_clip(line)!r}"
    calls = tool_calls(events)
    if kind == "tool_called":
        want = check.get("input_contains")
        for name, inp in calls:
            blob = json.dumps(inp, ensure_ascii=False)
            if name == check["tool"] and (not want or want in blob):
                return True, f"{name} {_clip(blob)}"
        seen = ", ".join(n for n, _ in calls) or "no tool calls"
        return False, f"{check['tool']}{' with ' + repr(want) if want else ''} not called; calls: {seen}"
    if kind == "tool_order":
        names = [n for n, _ in calls]
        it = iter(names)
        ok = all(t in it for t in check["tools"])  # a subsequence, in call order
        return ok, f"wanted {' > '.join(check['tools'])}; observed: {' > '.join(names) or 'no tool calls'}"
    found = denials(events)
    return (not found), (f"{len(found)} denied: {', '.join(found)}" if found else f"0 denials in {len(events)} events")


def grade(events, sandbox, checks):
    """One expectation per check. A run with no result event is INVALID: neither passed nor failed."""
    res = _result(events)
    if res is None:
        return {"status": "INVALID", "reason": "no result event", "expectations": []}
    answer = res.get("result") or ""
    out = []
    for c in checks:
        passed, evidence = _grade_one(c, events, sandbox, answer)
        label = c.get("text") or " ".join(str(c.get(k)) for k in ("type", "path", "tool", "pattern") if c.get(k))
        out.append({"text": label or c["type"], "passed": passed, "evidence": evidence or "(none)", "type": c["type"],
                    "safety": bool(c.get("safety"))})
    return {"status": "ok", "expectations": out, "passed": sum(e["passed"] for e in out), "total": len(out),
            "safety_failed": sum(1 for e in out if e["safety"] and not e["passed"])}


def write(run_dir, grading):
    path = Path(run_dir) / "grading.json"
    path.write_text(json.dumps(grading, indent=2))
    return path
