"""What every dashboard page shares: the page list, the filter bar's Filters and small formatters."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ...features.changes import BENCH_PROJECT


PAGES = {"overview": "Overview", "projects": "Projects", "sessions": "Sessions", "library": "Library",
         "benchmarks": "Benchmarks", "breakdowns": "Breakdowns", "managed": "Managed"}
RANGES = {"7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", "all": "All time"}


def _iso(dt):
    # transcript timestamps are '2026-10-20T14:59:27.168Z'; this prefix compares with them as text
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class Filters:
    """The filter bar: a range in days (None = all time) and optional project, model and skill."""

    def __init__(self, qs):
        one = lambda k: (qs.get(k) or [""])[0].strip()  # noqa: E731
        days = one("range") or "30"
        self.range = days if days in RANGES else "30"
        self.days = None if self.range == "all" else int(self.range)
        self.project, self.model, self.skill = one("project"), one("model"), one("skill")
        self.now = datetime.now(timezone.utc)

    def cond(self, shift=0):
        """(WHERE clause, params) for the report's helpers; shift=1 is the same-length range just before."""
        clauses, params = [f"s.project NOT LIKE '{BENCH_PROJECT}'"], []
        if self.days:
            end = self.now - timedelta(days=self.days * shift)
            clauses.append("r.ts >= ?")
            params.append(_iso(end - timedelta(days=self.days)))
            if shift:
                clauses.append("r.ts < ?")
                params.append(_iso(end))
        for col, value in (("s.project", self.project), ("r.model", self.model), ("r.skill", self.skill)):
            if value:
                clauses.append(f"{col} = ?")
                params.append(value)
        return "WHERE " + " AND ".join(clauses), tuple(params)

    def link(self, page, **change):
        q = self.query(**change)
        return f"/{page}?{q}" if q else f"/{page}"

    def query(self, **change):
        keep = {"range": self.range, "project": self.project, "model": self.model, "skill": self.skill, **change}
        return urlencode({k: v for k, v in keep.items() if v and not (k == "range" and v == "30")})

    def label(self):
        return RANGES[self.range].lower() if self.days else "all time"


def _q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def _dur(seconds):
    m, sec = divmod(int(seconds or 0), 60)
    return f"{m}m {sec:02d}s" if m else f"{sec}s"
