"""Budgets: <data home>/budgets.json against what was spent. Pure functions over the db; the CLI, the dashboard and the mod
print the result. API-eq dollars and tokens are measured from the requests table, per local day, with the same
attribution as `summary --by skill|agent`. Quota percentages (block_pct, weekly_pct) need statusline snapshots, which
tokscope does not store, so they report "no data".

    {"daily_usd": 50, "daily_tokens": 5000000, "block_pct": 80, "weekly_pct": 90,
     "skills": {"xia2": {"per_load_tokens": 200000, "daily_usd": 5}},
     "agents": {"reviewer": {"daily_usd": 10}}}"""

import json
from datetime import timezone

from .. import paths
from . import summary, tz
from .skills import versions

NEAR_PCT = 80
OK, NEAR, OVER, NODATA = 0, 10, 11, 30  # exit codes of `tokscope check --once`
STATES = {"ok": OK, "near": NEAR, "over": OVER, "nodata": NODATA}
_ROOT = {"daily_usd", "daily_tokens", "block_pct", "weekly_pct", "skills", "agents"}
_SKILL = {"per_load_tokens", "daily_usd", "daily_tokens"}
_AGENT = {"daily_usd", "daily_tokens"}
_ALL = 10 ** 9  # rows per group: every skill or agent, not the top 25


class BudgetError(ValueError):
    """budgets.json exists but cannot be used; the message says where and why."""


def _number(where, key, value, top=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or (top and value > top):
        raise BudgetError(f"{where}: {key!r} must be a number above 0{f' and at most {top}' if top else ''}, got {value!r}")
    return value


def _group(where, name, spec, allowed):
    if not isinstance(spec, dict):
        raise BudgetError(f"{where}: {name!r} must be an object with {', '.join(sorted(allowed))}")
    for key, value in spec.items():
        if key not in allowed:
            raise BudgetError(f"{where}: unknown key {key!r} in {name!r}; allowed: {', '.join(sorted(allowed))}")
        _number(where, f"{name}.{key}", value)
    return spec


def load(path=None):
    """The budgets as a dict, or None when there is no budgets.json. An unreadable or wrong file raises BudgetError."""
    path = path or paths.budgets()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise BudgetError(f"{path}: not valid JSON ({e})") from None
    where = str(path)
    if not isinstance(data, dict):
        raise BudgetError(f"{where}: must be a JSON object")
    for key, value in data.items():
        if key not in _ROOT:
            raise BudgetError(f"{where}: unknown key {key!r}; allowed: {', '.join(sorted(_ROOT))}")
        if key in ("skills", "agents"):
            if not isinstance(value, dict):
                raise BudgetError(f"{where}: {key!r} must be an object of name -> budget")
            for name, spec in value.items():
                _group(where, f"{key}.{name}", spec, _SKILL if key == "skills" else _AGENT)
        else:
            _number(where, key, value, 100 if key.endswith("_pct") else None)
    return data


def _state(pct):
    return "over" if pct >= 100 else "near" if pct >= NEAR_PCT else "ok"


def _item(key, label, used, limit, unit):
    pct = 100 * used / limit
    text = f"{used:,.0f} of {limit:,.0f} tokens" if unit == "tokens" else f"${used:,.2f} of ${limit:,.2f}"
    return {"key": key, "label": label, "used": used, "limit": limit, "unit": unit, "pct": round(pct, 1),
            "state": _state(pct), "text": f"{label} {pct:.0f}% ({text})"}


def _since():
    return tz.midnight().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _spent(conn, by, exclude=None):
    """{key: (tokens, usd)} since local midnight, from summary.rows so the attribution is the CLI table's."""
    where, params = "WHERE r.ts >= ?", [_since()]
    if exclude:
        where, params = where + " AND r.session_id != ?", [*params, exclude]
    return {r["key"]: (r["prompt_tokens"] + r["output_tokens"], r["cost_usd"])
            for r in summary.rows(conn, by, where, params, _ALL)}


def evaluate(conn, budgets, exclude_session=None):
    """One item per budget: key, label, used, limit, unit, pct, state (ok|near|over|nodata) and a line of text.
    exclude_session leaves one session out, to see what the budgets were before it."""
    items = []
    spent = {"": _spent(conn, "model", exclude_session), "skill": _spent(conn, "skill", exclude_session),
             "agent": _spent(conn, "agent", exclude_session)}
    day_tokens = sum(t for t, _ in spent[""].values())
    day_usd = sum(u for _, u in spent[""].values())
    if "daily_usd" in budgets:
        items.append(_item("daily_usd", "today", day_usd, budgets["daily_usd"], "usd"))
    if "daily_tokens" in budgets:
        items.append(_item("daily_tokens", "today", day_tokens, budgets["daily_tokens"], "tokens"))
    for key in ("block_pct", "weekly_pct"):
        if key in budgets:
            items.append({"key": key, "label": key, "used": None, "limit": budgets[key], "unit": "pct", "pct": None,
                          "state": "nodata", "text": f"{key} {budgets[key]:g}%: no quota snapshots to measure it"})
    for kind, by in (("skills", "skill"), ("agents", "agent")):
        for name, spec in (budgets.get(kind) or {}).items():
            tokens, usd = spent[by].get(name, (0, 0.0))
            for field, unit in (("daily_usd", "usd"), ("daily_tokens", "tokens")):
                if field in spec:
                    items.append(_item(f"{kind}.{name}.{field}", f"{by} {name} today", usd if unit == "usd" else tokens,
                                       spec[field], unit))
            if "per_load_tokens" in spec:
                rows = [r for r in versions(conn, name) if r["tokens_median"] is not None]
                if rows:  # the newest version with loads: what a load costs now
                    items.append(_item(f"{kind}.{name}.per_load_tokens", f"skill {name} per load", rows[-1]["tokens_median"],
                                       spec["per_load_tokens"], "tokens"))
                else:
                    items.append({"key": f"{kind}.{name}.per_load_tokens", "label": f"skill {name} per load", "used": None,
                                  "limit": spec["per_load_tokens"], "unit": "tokens", "pct": None, "state": "nodata",
                                  "text": f"skill {name} per load: no loads yet"})
    return items


def check(conn, budgets, exclude_session=None):
    """{"state", "exit", "items"}: the worst state of the measurable items; "nodata" with no budgets, nothing measurable or
    an empty db."""
    if budgets is None:
        return {"state": "nodata", "exit": NODATA, "items": [], "note": f"no budgets file at {paths.budgets()}"}
    items = evaluate(conn, budgets, exclude_session)
    measured = [i["state"] for i in items if i["state"] != "nodata"]
    if not measured or not conn.execute("SELECT 1 FROM requests LIMIT 1").fetchone():
        return {"state": "nodata", "exit": NODATA, "items": items, "note": "nothing to measure yet"}
    state = "over" if "over" in measured else "near" if "near" in measured else "ok"
    return {"state": state, "exit": STATES[state], "items": items}


def warnings(result):
    """The items at or above the near threshold, worst first."""
    return sorted((i for i in result["items"] if i["state"] in ("near", "over")), key=lambda i: -i["pct"])


def crossed(conn, budgets, session_id):
    """Items whose state got worse because of this session (daily budgets; a per-load median is not per session)."""
    rank = {"ok": 0, "near": 1, "over": 2}
    before = {i["key"]: i["state"] for i in evaluate(conn, budgets, session_id)}
    return [i for i in evaluate(conn, budgets) if i["state"] in rank and i["key"] in before
            and not i["key"].endswith("per_load_tokens") and rank[i["state"]] > rank.get(before[i["key"]], 0)]


def text(result):
    lines = [f"budgets: {result['state']}"]
    lines += [f"  {i['state']:<6} {i['text']}" for i in result["items"]]
    if result.get("note"):
        lines.append(f"  {result['note']}")
    return "\n".join(lines)
