"""Real-session numbers for an approved optimize run: the old and the new version of the skill, side by side."""
import statistics

from ..core import skills

MIN_LOADS = 5  # a side with fewer loads is too few to compare
BENCH = "%tokscope%-bench-%"


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def approved(conn, run_id):
    """(skill, old_version, new_version, at) of the newest approve of the run in `opt_applied`, or None."""
    if not _has_table(conn, "opt_applied"):
        return None
    row = conn.execute("SELECT skill, old_version, new_version, at FROM opt_applied WHERE run_id = ? AND action = 'approve' "
                       "ORDER BY at DESC LIMIT 1", (run_id,)).fetchone()
    return tuple(row) if row else None


def _turns(conn, keys):
    """{(session_id, prompt_idx): (tokens, cost)} per load: the requests of each turn split evenly over the turn's ok
    skill loads (of any skill), so a turn with several loads is not counted in full for each. Bench sessions left out."""
    sessions = {k[0] for k in keys}
    out = {}
    for sid in sessions:
        for i, tokens, cost in conn.execute(
                f"SELECT r.prompt_idx, sum({skills.TOKENS}), sum(COALESCE(r.cost_usd, 0)) FROM requests r "
                "JOIN sessions s USING (session_id) WHERE r.session_id = ? AND s.project NOT LIKE ? GROUP BY r.prompt_idx",
                (sid, BENCH)):
            out[(sid, i)] = (tokens or 0, cost or 0.0)
        for i, n in conn.execute("SELECT prompt_idx, count(*) FROM skill_calls WHERE session_id = ? AND COALESCE(failed, 0) = 0 "
                                 "GROUP BY prompt_idx", (sid,)):
            if (sid, i) in out and n > 1:
                t, c = out[(sid, i)]
                out[(sid, i)] = (t / n, c / n)
    return out


def _side(loads, failed, turns):
    """loads, failed: lists of (session_id, prompt_idx) of the ok and the failed loads of one version."""
    every = loads + failed
    measured = [turns[k] for k in loads if k in turns]
    n = len(every)
    return {"loads": n, "tokens_median": statistics.median(t for t, _ in measured) if measured else None,
            "cost_median": statistics.median(c for _, c in measured) if measured else None,
            "errors": len(failed), "error_rate": len(failed) / n if n else None, "few": n < MIN_LOADS}


def post_ship(conn, skill, old, new, at):
    """{"old": side, "new": side}: loads, median tokens and cost per load, errors and error rate from real sessions. A
    load counts by its version: the old version before `at`, the new one from `at` on; any other version (a later hand
    edit) and any load in a bench session is left out. A side is `few` under MIN_LOADS loads."""
    boundary = skills._dt(at)
    bench = {r[0] for r in conn.execute("SELECT session_id FROM sessions WHERE project LIKE ?", (BENCH,))}
    pick = {"old": ([], []), "new": ([], [])}
    for failed in (False, True):
        for sid, i, sk, ts, version, _ in skills.load_versions(conn, failed=failed):
            if sk != skill or not ts or version is None or sid in bench:
                continue
            if version == old and skills._dt(ts) < boundary:
                pick["old"][failed].append((sid, i))
            elif version == new and skills._dt(ts) >= boundary:
                pick["new"][failed].append((sid, i))
    turns = _turns(conn, [k for ok, bad in pick.values() for k in ok + bad])
    return {side: _side(ok, bad, turns) for side, (ok, bad) in pick.items()}
