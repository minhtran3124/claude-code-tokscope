"""List-price cost per request. Rates in USD per million tokens (claude-api skill, cached 2026-10-06)."""

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


def cost_usd(model, inp, out, cache_read, cw5m, cw1h):
    """Return list-price cost, or None when the model has no known rate."""
    key = normalize(model)
    if key not in RATES:
        return None
    r_in, r_out, r_read = RATES[key]
    if key in LONG_PROMPT:
        limit, mult = LONG_PROMPT[key]
        if inp + cache_read + cw5m + cw1h > limit:
            r_in, r_out, r_read = r_in * mult, r_out * mult, r_read * mult
    return (
        inp * r_in + out * r_out + cache_read * r_read + cw5m * r_in * WRITE_5M + cw1h * r_in * WRITE_1H
    ) / 1_000_000


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
