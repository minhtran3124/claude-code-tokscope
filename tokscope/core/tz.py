"""The day boundary: local time by default, TOKSCOPE_TZ or --timezone (an IANA name, e.g. UTC) to override.
Stored timestamps are UTC ('2026-10-20T14:59:27.168Z'); every day bucket, Today and --since/--until go through here."""

import os
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

_name = None


def set_zone(name):
    """Use this zone from now on (None: TOKSCOPE_TZ, else the system's). An unknown name raises ValueError."""
    global _name
    if name:
        try:
            ZoneInfo(name)
        except Exception:
            raise ValueError(f"unknown time zone {name!r}, e.g. UTC or Asia/Ho_Chi_Minh") from None
    _name = name or None
    _day_of_minute.cache_clear()


def zone():
    """The tzinfo in use; None means the system's local zone (what datetime.astimezone(None) uses)."""
    name = _name or os.environ.get("TOKSCOPE_TZ")
    return ZoneInfo(name) if name else None


def label():
    """Short name of the zone, for chart notes."""
    z = zone()
    return getattr(z, "key", None) or datetime.now().astimezone().tzname() or "local"


def now():
    return datetime.now(timezone.utc).astimezone(zone())


def local_day(ts):
    """'YYYY-MM-DD' of a stored UTC timestamp in the zone (None stays None). One answer per minute: a zone's offset
    changes on a whole minute, so the seconds never change the day, and the SQL function calls this once per request."""
    if not ts:
        return None
    return _day_of_minute(ts[:16])


@lru_cache(maxsize=262144)
def _day_of_minute(minute):
    return datetime.fromisoformat(minute).replace(tzinfo=timezone.utc).astimezone(zone()).strftime("%Y-%m-%d")


def midnight(day=None):
    """Local midnight (aware) of a date (default today)."""
    day = day or now().date()
    z = zone()
    return datetime.combine(day, time(), tzinfo=z) if z else datetime.combine(day, time()).astimezone()


def utc_bound(text, end=False):
    """Stored-timestamp prefix for a local ISO date: its first instant, or with end=True the first instant of the next day
    (compare with <). ValueError on a bad date."""
    day = date.fromisoformat(text) + timedelta(days=1 if end else 0)
    return midnight(day).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def register(conn):
    """Add the SQL function localday(ts) to a connection."""
    conn.create_function("localday", 1, local_day, deterministic=True)
    return conn
