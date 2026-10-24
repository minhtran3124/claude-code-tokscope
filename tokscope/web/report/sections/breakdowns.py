"""The Breakdowns section: by week, MCP server, tool, phase, owner, skill and subagent type."""

import html
from datetime import datetime, timedelta, timezone
from statistics import median

from ....core import skills, tz
from ... import charts
from ....core.calls import est_tokens, mcp_server
from ....core.ingest import CARRIED
from ..common import TOKENS
from ..widgets import _pc, _section, _table, _tok, _usd


def _week_skills(conn, cond, params, now, n=10):
    """Skills ranked by their tokens in the last 7 days, with the 7 days before them for the change."""
    mid, start = (now - timedelta(days=7)).isoformat(), (now - timedelta(days=14)).isoformat()
    rows = conn.execute(
        f"SELECT skill, max(phase), sum(CASE WHEN r.ts >= ? THEN {TOKENS} ELSE 0 END), "
        f"sum(CASE WHEN r.ts < ? THEN {TOKENS} ELSE 0 END) FROM requests r JOIN sessions s USING (session_id) {cond} "
        f"AND skill IS NOT NULL AND r.ts >= ? AND r.ts < ? GROUP BY skill",
        (mid, mid, *params, start, now.isoformat())).fetchall()
    return sorted((r for r in rows if r[2]), key=lambda r: -r[2])[:n]


def _weekly_phases(conn, cond, params, today=None):
    """Tokens per phase per calendar week (Monday start), oldest first; the current week is labelled as partial."""
    weeks = {}
    for day, phase, t in conn.execute(
            f"SELECT localday(r.ts), COALESCE(phase,'unscoped'), sum({TOKENS}) FROM requests r JOIN sessions s "
            f"USING (session_id) {cond} GROUP BY 1, 2", params):
        d = datetime.fromisoformat(day).date()
        by = weeks.setdefault(d - timedelta(days=d.weekday()), {})
        by[phase] = by.get(phase, 0) + (t or 0)
    today = today or tz.now().date()
    return [(f"{w:%b %d}" + (" so far" if w > today - timedelta(days=7) else ""), weeks[w]) for w in sorted(weeks)]


def _pct(q):
    return lambda xs: xs[min(len(xs) - 1, int(q * len(xs)))]


def _breakdowns(conn, cond, params):
    base = f"FROM requests r JOIN sessions s USING (session_id) {cond}"
    q = lambda sql: conn.execute(sql, params).fetchall()  # noqa: E731
    real_total = q(f"SELECT sum({TOKENS}) {base}")[0][0] or 0
    total = real_total or 1
    share = lambda t: f"{(t or 0) / total:.1%}"  # noqa: E731
    phase = q(f"SELECT COALESCE(phase,'unscoped'), count(DISTINCT session_id), sum({TOKENS}), "
              f"sum(CASE WHEN {CARRIED} THEN {TOKENS} ELSE 0 END), sum(output), sum(cost_usd) {base} GROUP BY 1 ORDER BY 3 DESC")
    carried = sum(c for _, _, _, c, _, _ in phase)
    owner = q(f"SELECT CASE WHEN agent_id IS NULL THEN 'main thread' ELSE 'agent: ' || agent_type END, sum({TOKENS}), sum(output), "
              f"sum(cost_usd) {base} GROUP BY 1 ORDER BY 2 DESC")
    loads = dict(conn.execute("SELECT skill, count(*) FROM skill_calls GROUP BY skill"))
    skills = q(f"SELECT skill, count(DISTINCT session_id), sum({TOKENS}), sum(cost_usd), "
               f"sum(CASE WHEN agent_id IS NULL THEN {TOKENS} ELSE 0 END), sum(CASE WHEN agent_id IS NOT NULL THEN {TOKENS} ELSE 0 END) "
               f"{base} AND skill IS NOT NULL GROUP BY skill ORDER BY 3 DESC LIMIT 30")
    runs = q(f"SELECT agent_type, sum({TOKENS}), sum(output), sum(cost_usd), group_concat(DISTINCT model) {base} "
             f"AND agent_id IS NOT NULL GROUP BY session_id, agent_id")
    by_type = {}
    for t, tk, o, c, m in runs:
        by_type.setdefault(t, []).append((tk or 0, o or 0, c or 0, m or ""))
    agent_rows, spread = [], []
    for t, rs in sorted(by_type.items(), key=lambda kv: -sum(r[0] for r in kv[1]))[:20]:
        tks = sorted(r[0] for r in rs)
        models = sorted({x.removeprefix("claude-") for r in rs for x in r[3].split(",") if x})
        agent_rows.append((t, len(rs), sum(tks), _tok(median(tks)), _tok(_pct(0.9)(tks)),
                           (_usd(median(r[2] for r in rs)), "u"), (", ".join(models), "lm")))
        spread.append((t, len(rs), _pct(0.1)(tks), median(tks), _pct(0.9)(tks)))
    calls_rows = conn.execute(
        f"SELECT session_id, name, count(*), sum(result_chars) FROM tool_calls WHERE name != 'Agent' "
        f"AND session_id IN (SELECT session_id FROM requests r JOIN sessions s USING (session_id) {cond}) GROUP BY 1, 2",
        params).fetchall()
    servers, tools = {}, {}
    for sid, name, n, chars in calls_rows:
        target, key = (servers, mcp_server(name)) if name.startswith("mcp__") else (tools, name)
        g = target.setdefault(key, [0, set(), 0])
        g[0] += n
        g[1].add(sid)
        g[2] += chars or 0

    def call_rows(groups):
        return [(k, n, len(sids), est_tokens(chars), _tok(est_tokens(chars) / n))
                for k, (n, sids, chars) in sorted(groups.items(), key=lambda kv: -kv[1][2])[:25]]
    def usage(groups):
        return [(k, n, est_tokens(chars) / n, est_tokens(chars)) for k, (n, _, chars) in groups.items()]

    week = _week_skills(conn, cond, params, datetime.now(timezone.utc))
    week_rows = [(sk, ph or "", this, (_tok(last) if last else "–", "lm"),
                  (charts.change_text(last, this), "lm"))
                 for sk, ph, this, last in week]
    call_note = "~ tokens = size of the results put into the context, estimated at 4 characters per token"
    pc = _pc
    top = lambda groups, key: max(groups.items(), key=key)  # noqa: E731
    # one finding per section, each worked out from the numbers the section already shows
    if week:
        this_t, last_t = sum(w[2] for w in week), sum(w[3] for w in week)
        f_week = (f"{_tok(this_t)} this week, {charts.change_text(last_t, this_t)} on last week; {html.escape(week[0][0])} leads"
                  if last_t else f"{_tok(this_t)} this week, nothing the week before; {html.escape(week[0][0])} leads")
    srv_t = sum(c for _, _, c in servers.values())
    tool_t = sum(c for _, _, c in tools.values())
    f_srv = f_tool = p_srv = p_tool = None
    if servers:
        k, g = top(servers, lambda kv: kv[1][2])
        p_srv = g[2] / srv_t if srv_t else 0
        f_srv = f"{html.escape(k)} holds {pc(p_srv)} of MCP result tokens across {len(servers)} server{'s' * (len(servers) != 1)}"
    if tools:
        k, g = top(tools, lambda kv: kv[1][2])
        p_tool = g[2] / tool_t if tool_t else 0
        f_tool = f"{html.escape(k)} returns {pc(p_tool)} of tool result tokens across {len(tools)} tool{'s' * (len(tools) != 1)}"
    has_tokens = bool(real_total)
    if has_tokens:
        p_phase = (phase[0][2] or 0) / real_total
        f_phase = f"{html.escape(phase[0][0])} is the largest phase at {share(phase[0][2])}; {share(carried)} is carried"
        sub_t = sum(t or 0 for o, t, *_ in owner if o != "main thread")
        p_owner = sub_t / real_total
        f_owner = (f"Subagents use {pc(p_owner)} of all tokens" if sub_t else "No subagent ran: the main thread has every token")
    if skills:
        p_skill = (skills[0][2] or 0) / real_total if has_tokens else 0
        n_skills = q(f"SELECT count(DISTINCT skill) {base} AND skill IS NOT NULL")[0][0]
        f_skill = f"{html.escape(skills[0][0])} uses {pc(p_skill)} of all tokens; {n_skills} skill{'s' * (n_skills != 1)} loaded"
    if by_type:
        sums = {t: sum(r[0] for r in rs) for t, rs in by_type.items()}
        all_runs, all_t = sum(len(rs) for rs in by_type.values()), sum(sums.values())
        k = max(sums, key=sums.get)
        p_type = sums[k] / all_t if all_t else 0
        f_type = (f"{all_runs:,} run{'s' * (all_runs != 1)} across {len(by_type)} type{'s' * (len(by_type) != 1)}; "
                  f"{html.escape(str(k))} uses {pc(p_type)} of subagent tokens")
    ingest = "Run <code>tokscope ingest</code> after a Claude Code session to fill it."
    return "".join([
        _section("Week over week", f_week if week else "No skill loaded in the last 7 days",
                 "the last 7 days against the 7 before, per skill; ranked by this week",
                 (charts.dumbbell([(sk, last, this) for sk, _, this, last in week], "tokens")
                  + _table(["skill", "phase", "this week", "last week", "change"], week_rows, 2)) if week else "", "by-week",
                 empty=None if week else ("Nothing to compare yet",
                                          "A skill that loads in the last 7 days shows here against the 7 before. " + ingest)),
        _section("By MCP server", f_srv or "No MCP server called",
                 call_note + "; the bar is each server's share of all MCP result tokens",
                 charts.share_bar([(k, est_tokens(c)) for k, (_, _, c) in servers.items()], "~result tokens")
                 + _table(["server", "calls", "sessions", "~result tokens", "per call"], call_rows(servers), 3), "by-mcp", p_srv,
                 empty=None if servers else ("No MCP calls yet",
                                             "Each MCP server a session calls shows here with its result size. Add one with "
                                             "<code>claude mcp add</code>, use it, then run <code>tokscope ingest</code>.")),
        _section("By tool", f_tool or "No tool called",
                 call_note + "; Agent calls are under subagent types. Top right = called often and heavy each time",
                 charts.scatter(usage(tools), "calls", "~tokens per call")
                 + _table(["tool", "calls", "sessions", "~result tokens", "per call"], call_rows(tools), 3), "by-tool", p_tool,
                 empty=None if tools else ("No tool calls yet", "Every tool a session calls (Read, Bash, Grep) shows here. " + ingest)),
        _section("By phase", f_phase if has_tokens else "No tokens in this range",
                 f"direct = the phase's skill ran in that prompt; carried = a later prompt with no skill, which keeps "
                 f"the last phase ({share(carried)} of all tokens); rows sum to the total; the chart splits each calendar week",
                 charts.weekly_columns(_weekly_phases(conn, cond, params), "tokens")
                 + _table(["phase", "sessions", "tokens", "direct", "carried", "output", "API-eq", "share"],
                          [(p, s, t, _tok((t or 0) - (cr or 0)), f"{_tok(cr)} ({(cr or 0) / (t or 1):.0%})" if cr else "–",
                            _tok(o), (_usd(c), "u"), share(t)) for p, s, t, cr, o, c in phase], 2), "by-phase",
                 p_phase if has_tokens else None,
                 empty=None if has_tokens else ("No phases yet", "A phase appears once a skill in the workflow runs. " + ingest)),
        _section("By owner", f_owner if has_tokens else "No tokens in this range",
                 "main thread vs each subagent type; rows sum to the total",
                 charts.share_bar([(o, t or 0) for o, t, *_ in owner], "tokens")
                 + _table(["owner", "tokens", "output", "API-eq", "share"],
                          [(o, t, _tok(x), (_usd(c), "u"), share(t)) for o, t, x, c in owner[:20]], 1), "by-owner",
                 p_owner if has_tokens else None,
                 empty=None if has_tokens else ("No tokens yet", "The main thread and each subagent type show here. " + ingest)),
        _section("By skill", f_skill if skills else "No skill loaded",
                 "requests while a skill was loaded in that prompt. tokens = main thread + the subagents the skill "
                 "started; the subagents column is also counted under By owner, so do not add the two tables. "
                 "Top right = loaded often and heavy each time",
                 charts.scatter([(sk, loads.get(sk, 0), (t or 0) / loads[sk], t or 0) for sk, _, t, *_ in skills if loads.get(sk)],
                                "loads", "tokens per load")
                 + _table(["skill", "loads", "sessions", "tokens", "main thread", "subagents", "per load", "API-eq"],
                          [(sk, loads.get(sk, 0), s, t, _tok(m), _tok(a) if a else "–", _tok((t or 0) / max(loads.get(sk, 0), 1)),
                            (_usd(c), "u")) for sk, s, t, c, m, a in skills], 3), "by-skill", p_skill if skills else None,
                 empty=None if skills else ("No skill has loaded yet", "Load a skill in Claude Code (a slash command or the Skill tool) "
                                            "and its tokens show here. " + ingest)),
        _section("Subagent types", f_type if by_type else "No subagent ran",
                 "one run = one subagent transcript; the line spans p10 to p90 of a run, the dot is the median",
                 charts.ranges(spread[:12], "tokens")
                 + _table(["agent type", "runs", "tokens", "median", "p90", "median API-eq", "models"], agent_rows, 2), "agent-types",
                 p_type if by_type else None,
                 empty=None if by_type else ("No subagent runs yet", "Each subagent type shows here once Claude Code starts one "
                                             "(the Agent tool). " + ingest)),
    ])
