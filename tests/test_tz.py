import argparse
import os
import unittest

from tokscope import cli
from tokscope.core import tz
from tokscope.core.ingest import connect
from tokscope.web.dashboard import Filters
from tokscope.web.dashboard.pages import overview as overview_page

SAIGON = "Asia/Ho_Chi_Minh"  # UTC+7


class DayBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(tz.set_zone, None)
        self.addCleanup(os.environ.pop, "TOKSCOPE_TZ", None)
        self.conn = connect(":memory:")
        self.conn.execute("INSERT INTO sessions (session_id, project, cwd, title) VALUES ('s1','p','/p','t')")
        # 23:30Z on 10-21 is 06:30 on 10-22 in UTC+7
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, input, output, cache_read, "
                          "cache_write_5m, cache_write_1h, cost_usd) VALUES ('s1','a','2026-10-21T23:30:00.000Z','m',1,100,0,0,0,0,0.1)")

    def days(self):
        return [d for d, *_ in overview_page._days(self.conn, Filters({"range": ["all"]}))]

    def count(self, since=None, until=None):
        where, params = cli._filters(argparse.Namespace(since=since, until=until, project=None))
        return self.conn.execute(f"SELECT count(*) FROM requests r JOIN sessions s USING (session_id) {where}", params).fetchone()[0]

    def test_a_request_near_midnight_lands_on_the_local_day(self):
        tz.set_zone(SAIGON)
        self.assertEqual(self.days(), ["2026-10-22"])

    def test_timezone_utc_keeps_the_utc_day(self):
        tz.set_zone("UTC")
        self.assertEqual(self.days(), ["2026-10-21"])

    def test_env_var_sets_the_zone(self):
        os.environ["TOKSCOPE_TZ"] = SAIGON
        self.assertEqual(self.days(), ["2026-10-22"])

    def test_midnight_is_the_same_boundary_as_the_buckets(self):
        tz.set_zone(SAIGON)
        self.assertEqual(tz.utc_bound("2026-10-22"), "2026-10-21T17:00:00")
        self.assertEqual(tz.utc_bound("2026-10-22", end=True), "2026-10-22T17:00:00")
        self.assertEqual(tz.local_day("2026-10-21T16:59:59.000Z"), "2026-10-21")
        self.assertEqual(tz.local_day("2026-10-21T17:00:00.000Z"), "2026-10-22")

    def test_since_and_until_are_local_dates(self):
        tz.set_zone(SAIGON)
        self.assertEqual(self.count(since="2026-10-22", until="2026-10-22"), 1)  # local 10-22, though the UTC date is 10-21
        self.assertEqual(self.count(until="2026-10-21"), 0)
        tz.set_zone("UTC")
        self.assertEqual(self.count(since="2026-10-22"), 0)

    def test_unknown_zone_is_an_error(self):
        with self.assertRaises(ValueError):
            tz.set_zone("Nowhere/Land")


if __name__ == "__main__":
    unittest.main()
