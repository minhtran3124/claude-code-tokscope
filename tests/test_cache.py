import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tokscope.core import cache
from tokscope.core.ingest import connect
from tokscope.web.report.sections.breakdowns import _breakdowns

T0 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
COND, PARAMS = "WHERE s.project NOT LIKE ?", ("%bench%",)
MODEL = "claude-sonnet-4-6"  # input $3 per million, so a 5 minute write is $3.75 per million


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(Path(tempfile.mkdtemp()) / "t.db")
        self.conn.execute("INSERT INTO sessions (session_id, project) VALUES ('s1', '-home-u-app')")
        self.n = 0

    def req(self, secs, inp, cr, cw5=0, cw1=0, skill="a", agent=None, session="s1"):
        self.n += 1
        self.conn.execute(
            "INSERT INTO requests (session_id, request_key, ts, model, agent_id, agent_type, skill, input, output, cache_read, "
            "cache_write_5m, cache_write_1h, cost_usd) VALUES (?,?,?,?,?,?,?,?,0,?,?,?,0)",
            (session, f"k{self.n}", (T0 + timedelta(seconds=secs)).isoformat(), MODEL, agent, agent and "reviewer", skill, inp,
             cr, cw5, cw1))

    def fixture(self):
        self.req(0, 100, 0, cw5=10000)          # cold start
        self.req(60, 100, 10000, cw5=500)       # warm
        self.req(460, 100, 0, cw5=10500)        # 400 s idle, cache gone: TTL
        self.req(490, 100, 10500, cw5=200)      # warm
        self.req(520, 100, 100, cw5=8000)       # 30 s later, prefix re-written: tools or system prompt changed

    def test_hit_ratio_and_cache_write_cost_match_a_hand_calculation(self):
        self.fixture()
        reqs, misses = cache.scan(self.conn, COND, PARAMS)
        t = cache.totals(reqs, misses)
        # reads 20600, writes 29200, uncached input 500 -> 20600 / 50300
        self.assertAlmostEqual(t["hit_ratio"], 20600 / 50300)
        self.assertAlmostEqual(t["write_usd"], 29200 * 3.75 / 1e6)
        for by, key in (("session", "s1"), ("skill", "a"), ("model", MODEL), ("agent", "main")):
            (d,) = cache.rows(reqs, by)
            self.assertEqual(d["key"], key)
            self.assertAlmostEqual(d["hit_ratio"], 20600 / 50300)
            self.assertAlmostEqual(d["write_usd"], 29200 * 3.75 / 1e6)

    def test_the_one_hour_write_is_priced_at_twice_the_input_rate(self):
        self.req(0, 0, 0, cw1=1_000_000)
        reqs, _ = cache.scan(self.conn, COND, PARAMS)
        self.assertAlmostEqual(reqs[0]["write_usd"], 6.0)

    def test_a_ttl_gap_and_a_changed_prefix_are_flagged_with_their_causes(self):
        self.fixture()
        _, misses = cache.scan(self.conn, COND, PARAMS)
        self.assertEqual([(m["cause"], m["recache"]) for m in misses], [("ttl_expired_5m", 10500), ("prefix_changed", 8000)])
        self.assertAlmostEqual(misses[0]["recache_usd"], 10500 * 3.75 / 1e6)

    def test_a_gap_over_an_hour_is_the_one_hour_ttl(self):
        self.req(0, 0, 0, cw1=5000)
        self.req(10, 0, 5000)
        self.req(4000, 0, 0, cw1=5000)
        self.assertEqual([m["cause"] for m in cache.scan(self.conn, COND, PARAMS)[1]], ["ttl_expired_1h"])

    def test_a_compact_between_two_requests_is_not_a_miss_and_a_small_write_is_not_either(self):
        self.req(0, 0, 0, cw5=5000)
        self.req(10, 0, 5000, cw5=0)
        self.conn.execute("INSERT INTO turn_events VALUES ('s1', ?, 0, NULL, NULL, NULL, 'compact')",  # what ingest writes
                          ((T0 + timedelta(seconds=15)).isoformat(),))
        self.req(20, 0, 0, cw5=5000)
        self.req(30, 0, 5000)
        self.req(40, 0, 0, cw5=100)   # below MIN_WRITE
        self.assertEqual(cache.scan(self.conn, COND, PARAMS)[1], [])

    def test_a_subagent_thread_is_compared_with_itself_not_with_the_main_thread(self):
        self.req(0, 0, 50000, cw5=0)
        self.req(5, 0, 0, cw5=9000, agent="a1")  # first request of a subagent: a cold start, not a miss
        self.conn.execute("INSERT INTO subagents (session_id, agent_id, agent_type) VALUES ('s1', 'a1', 'reviewer')")
        reqs, misses = cache.scan(self.conn, COND, PARAMS)
        self.assertEqual(misses, [])
        self.assertEqual({d["key"] for d in cache.rows(reqs, "agent")}, {"main", "reviewer"})

    def test_official_miss_causes_need_snapshots_and_are_labelled_official(self):
        self.fixture()
        self.assertIsNone(cache.official(self.conn, COND, PARAMS))
        pc = {"misses": 7, "miss_recache_tokens": 310000, "miss_causes": {"tools_changed": 5, "ttl_expired_5m": 2}}
        self.conn.execute("INSERT INTO statusline_snapshots VALUES ('s1', '2026-10-20T13:00:00+00:00', ?)", (json.dumps(pc),))
        self.assertEqual(cache.official(self.conn, COND, PARAMS),
                         {"causes": {"tools_changed": 5, "ttl_expired_5m": 2}, "misses": 7, "recache_tokens": 310000, "sessions": 1})
        page = _breakdowns(self.conn, COND, PARAMS)
        self.assertIn("official: Claude Code statusline prompt_cache", page)
        self.assertIn("tools_changed", page)

    def snap(self, secs, misses, tokens, causes):
        pc = {"misses": misses, "miss_recache_tokens": tokens, "miss_causes": causes}
        self.conn.execute("INSERT INTO statusline_snapshots VALUES ('s1', ?, ?)",
                          ((T0 + timedelta(seconds=secs)).isoformat(), json.dumps(pc)))

    def test_official_misses_are_grouped_by_the_skill_running_when_they_grew(self):
        self.fixture()
        self.req(550, 100, 0, cw5=9000, skill="b")
        self.snap(100, 2, 100000, {"ttl_expired_5m": 2})                       # skill a was running
        self.snap(600, 7, 310000, {"ttl_expired_5m": 2, "tools_changed": 5})  # +5 while skill b ran
        self.assertEqual(cache.official_by(self.conn, "skill", COND, PARAMS), [
            {"key": "b", "misses": 5, "recache_tokens": 210000, "causes": {"tools_changed": 5}},
            {"key": "a", "misses": 2, "recache_tokens": 100000, "causes": {"ttl_expired_5m": 2}}])
        self.assertEqual(cache.official(self.conn, COND, PARAMS)["misses"], 7)  # the latest snapshot still totals
        self.assertIn("Official misses by skill", _breakdowns(self.conn, COND, PARAMS))
        self.conn.execute("DELETE FROM statusline_snapshots")
        self.assertIsNone(cache.official_by(self.conn, "skill", COND, PARAMS))

    def test_record_snapshot_keeps_counters_only_and_skips_an_unchanged_one(self):
        data = {"session_id": "s1", "prompt_cache": {"misses": 3, "miss_recache_tokens": 900, "hit_ratio": 0.8,
                                                     "miss_causes": {"tools_changed": 3}, "tools_added": ["mcp__secret__x"]}}
        self.assertTrue(cache.record_snapshot(self.conn, data))
        self.assertFalse(cache.record_snapshot(self.conn, data))
        blob = self.conn.execute("SELECT prompt_cache FROM statusline_snapshots").fetchone()[0]
        self.assertNotIn("secret", blob)
        self.assertEqual(json.loads(blob)["miss_causes"], {"tools_changed": 3})
        for bad in (None, {}, {"session_id": "s1"}, {"prompt_cache": {}}, {"session_id": "s1", "prompt_cache": "x"}):
            self.assertFalse(cache.record_snapshot(self.conn, bad))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM statusline_snapshots").fetchone()[0], 1)

    def test_the_section_states_the_finding_and_has_an_empty_state(self):
        page = _breakdowns(self.conn, COND, PARAMS)
        self.assertIn("No cache data yet", page)
        self.fixture()
        page = _breakdowns(self.conn, COND, PARAMS)
        head = re.search(r'id="cache"><summary>.*?</summary>', page, re.S).group(0)
        self.assertIn("41% of prompt tokens came from the cache", head)
        self.assertIn("2 likely misses", head)
        self.assertIn("top cause ttl_expired_5m", head)
        self.assertIn("keep the session warm", page)

    def test_the_overview_finding_covers_the_last_7_days_only(self):
        from tokscope.web.dashboard.common import Filters
        from tokscope.web.dashboard.pages.overview import _cache_finding
        f = Filters({})
        self.assertEqual(_cache_finding(self.conn, f), "")
        now = datetime.now(timezone.utc)
        for base, session in ((now - timedelta(days=1), "s1"), (now - timedelta(days=20), "old")):
            self.conn.execute("INSERT OR IGNORE INTO sessions (session_id, project) VALUES (?, '-home-u-app')", (session,))
            for secs, cr, cw in ((0, 0, 5000), (10, 5000, 0), (500, 0, 5000)):
                self.n += 1
                self.conn.execute(
                    "INSERT INTO requests (session_id, request_key, ts, model, input, output, cache_read, cache_write_5m, "
                    "cache_write_1h, cost_usd) VALUES (?,?,?,?,0,0,?,?,0,0)",
                    (session, f"k{self.n}", (base + timedelta(seconds=secs)).isoformat(), MODEL, cr, cw))
        out = _cache_finding(self.conn, f)
        self.assertIn("1 likely miss,", out)
        self.assertIn("top cause: ttl_expired_5m", out)


if __name__ == "__main__":
    unittest.main()


class OverridesOnceTest(CacheTest):
    def test_pricing_json_read_once_per_scan_and_load(self):
        from unittest import mock
        from tokscope.core import context, pricing
        for i in range(5):
            self.req(i * 10, 10, 1000, 100)
        self.conn.execute("INSERT INTO tool_calls (session_id, name, result_chars, model, ts) VALUES ('s1','Read',400,?,?)",
                          (MODEL, T0.isoformat()))
        with mock.patch.object(pricing, "overrides", wraps=pricing.overrides) as m:
            cache.scan(self.conn)
            context.load(self.conn)
        self.assertEqual(m.call_count, 2)
