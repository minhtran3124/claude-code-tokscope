"""List-price cost per request. Rates in USD per million tokens (claude-api skill, cached 2026-10-06)."""

import hashlib
import json

# every dollar figure tokscope shows is this estimate; the wording follows https://code.claude.com/docs/en/costs
COSTS_DOC = "https://code.claude.com/docs/en/costs"
API_EQ_NOTE = ("API-eq = these tokens at Anthropic API list prices, an estimate. With an API key that is close to the bill. "
               "On a Pro, Max, Team or Enterprise plan you are not billed per token: Claude Code is limited by a rolling "
               "5-hour session limit and a weekly limit.")

# model -> (input, output, cache_read)
RATES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-opus-4-7": (5.0, 25.0, 0.50),
    "claude-opus-4-6": (5.0, 25.0, 0.50),
    # cache read per Claude Code 2.1.304 cost_usd (OTel), not the $0.20 in the claude-api skill doc
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
    "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-mythos-5": (10.0, 50.0, 1.0),
    "claude-opus-4-5": (5.0, 25.0, 0.50),
    "claude-opus-4-1": (15.0, 75.0, 1.50),
    "claude-opus-4": (15.0, 75.0, 1.50),
    "claude-sonnet-4-5": (3.0, 15.0, 0.30),
    "claude-sonnet-4": (3.0, 15.0, 0.30),
    "claude-haiku-3-5": (0.80, 4.0, 0.08),
    "claude-3-5-haiku": (0.80, 4.0, 0.08),
}
# Haiku 5.5 bills prompts above 100K tokens at 5x
LONG_PROMPT = {"claude-haiku-5-5": (100_000, 5.0)}
WRITE_5M, WRITE_1H = 1.25, 2.0


def normalize(model):
    # dated snapshots (claude-haiku-4-5-20251001) share the undated rate
    if model in RATES:
        return model
    base, _, stamp = model.rpartition("-")
    return base if base in RATES and len(stamp) == 8 and stamp.isdigit() else model  # a snapshot date, not a minor version


# fast mode bills every token category at 2x (Opus 5.5 $8/$40, Opus 5 and 4.8 $10/$50); US-only inference at 1.1x on 4.6+
FAST = {"claude-opus-5-5": 2.0, "claude-opus-5": 2.0, "claude-opus-4-8": 2.0}
US_MULT = 1.1
PRE_US = ("claude-opus-4-5", "claude-opus-4-1", "claude-opus-4", "claude-sonnet-4-5", "claude-sonnet-4", "claude-haiku-4-5",
          "claude-haiku-3-5", "claude-3-5-haiku")
WEB_SEARCH_PER_1000 = 10.0


def overrides():
    """pricing.json in the data home: {"web_search_per_1000": n, "<model>": {"input", "output", "cache_read", "fast", "us"}}."""
    from .. import paths  # lazy: paths.home() reads the environment at call time
    try:
        data = json.loads((paths.home() / "pricing.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _model_rates(key, ov):
    """(input, output, cache_read, fast multiplier or None, us multiplier or None) with the override applied."""
    o = ov.get(key) if isinstance(ov.get(key), dict) else {}
    base = RATES.get(key)
    if base is None and not all(_num(o.get(k)) is not None for k in ("input", "output", "cache_read")):
        return None
    base = base or (0, 0, 0)
    r = [_num(o.get(k)) if _num(o.get(k)) is not None else b for k, b in zip(("input", "output", "cache_read"), base)]
    fast = _num(o["fast"]) if _num(o.get("fast")) is not None else FAST.get(key)
    us = _num(o["us"]) if _num(o.get("us")) is not None else (None if key in PRE_US else US_MULT)
    return (*r, fast, us)


def fingerprint():
    """Changes whenever a rate, a multiplier or pricing.json changes, so stored costs know to refresh."""
    blob = json.dumps([RATES, LONG_PROMPT, FAST, US_MULT, PRE_US, WEB_SEARCH_PER_1000, WRITE_5M, WRITE_1H, overrides()],
                      sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()


def cost_usd(model, inp, out, cache_read, cw5m, cw1h, speed=None, geo=None, searches=0, ov=None):
    """Return list-price cost, or None when the model has no known rate."""
    ov = overrides() if ov is None else ov
    key = normalize(model)
    rates = _model_rates(key, ov)
    if rates is None:
        return None
    r_in, r_out, r_read, fast, us = rates
    mult = 1.0
    if key in LONG_PROMPT:
        limit, m = LONG_PROMPT[key]
        if inp + cache_read + cw5m + cw1h > limit:
            mult *= m
    if speed == "fast" and fast:
        mult *= fast
    if geo == "us" and us:
        mult *= us
    web = _num(ov.get("web_search_per_1000"))
    web = WEB_SEARCH_PER_1000 if web is None else web
    return (
        (inp * r_in + out * r_out + cache_read * r_read + cw5m * r_in * WRITE_5M + cw1h * r_in * WRITE_1H) * mult
        + (searches or 0) * web * 1000
    ) / 1_000_000


def refresh_costs(conn):
    """Recompute every stored cost when the price table or pricing.json changed since the last run; no re-ingest."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    fp = fingerprint()
    row = conn.execute("SELECT v FROM meta WHERE k = 'pricing'").fetchone()
    if row and row[0] == fp:
        return
    ov = overrides()
    rows = conn.execute("SELECT model, input, output, cache_read, cache_write_5m, cache_write_1h, speed, inference_geo, "
                        "web_search_requests, rowid FROM requests").fetchall()
    conn.executemany("UPDATE requests SET cost_usd = ? WHERE rowid = ?",
                     [(cost_usd(*r[:9], ov=ov), r[9]) for r in rows])
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('pricing', ?)", (fp,))
    conn.commit()


def unpriced(conn, cond="", params=()):
    """[(model, requests)] in the range whose cost is NULL; cond is a WHERE clause over requests r and sessions s."""
    cond = f"{cond} AND" if cond else "WHERE"
    return conn.execute(
        f"SELECT r.model, count(*) FROM requests r JOIN sessions s USING (session_id) {cond} r.cost_usd IS NULL "
        f"GROUP BY r.model ORDER BY 2 DESC", tuple(params)).fetchall()


def unpriced_text(rows):
    """One line naming the unpriced requests and models, or '' when every request is priced."""
    if not rows:
        return ""
    return (f"unpriced: {sum(n for _, n in rows):,} requests ({', '.join(str(m) for m, _ in rows)}) "
            "have no list price and count as $0, so API-eq is too low")


def cache_read_rate(model, ov=None):
    """USD per token a request pays to re-read cached context, or None when the model has no known rate."""
    rates = _model_rates(normalize(model or ""), overrides() if ov is None else ov)
    return None if rates is None else rates[2] / 1_000_000
