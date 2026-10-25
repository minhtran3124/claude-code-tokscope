import gzip
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from tokscope.integrations import otel_receiver as r

SAMPLE = {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"body": {"stringValue": "claude_code.api_request"}}]}]}]}


class ReceiverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.srv = r.make_server("127.0.0.1", 0, self.dir, max_body=20_000)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, path, body, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request("POST", path, body, {"Content-Type": "application/json", **(headers or {})})
        resp = c.getresponse()
        resp.read()
        c.close()
        return resp.status

    def files(self):
        return list(self.dir.glob("*.jsonl"))

    def test_a_logs_post_is_one_jsonl_line(self):
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE)), 200)
        (f,) = self.files()
        self.assertTrue(f.name.startswith("logs-"))
        row = json.loads(f.read_text())
        self.assertEqual((row["signal"], row["body"]), ("logs", SAMPLE))

    def test_parallel_large_posts_keep_every_line_whole(self):
        # each line is over the 8 KiB io buffer, so an unlocked append is several writes and can interleave
        bodies = [json.dumps({"id": i, "pad": "x" * 9000}) for i in range(16)]
        threads = [threading.Thread(target=self.post, args=("/v1/logs", b)) for b in bodies]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        (f,) = self.files()
        rows = [json.loads(line) for line in f.read_text().splitlines()]
        self.assertEqual(sorted(row["body"]["id"] for row in rows), list(range(16)))

    def test_gzip_body_is_accepted(self):
        self.assertEqual(self.post("/v1/metrics", gzip.compress(json.dumps(SAMPLE).encode()), {"Content-Encoding": "gzip"}), 200)
        self.assertEqual(len(self.files()), 1)

    def test_oversized_body_is_413_and_not_written(self):
        self.assertEqual(self.post("/v1/logs", json.dumps({"x": "a" * 20_000})), 413)
        self.assertEqual(self.files(), [])

    def test_gzip_bomb_is_refused_and_not_written(self):
        bomb = gzip.compress(b'{"x": "' + b"a" * 5_000_000 + b'"}')
        self.assertLess(len(bomb), 10_000)
        self.assertEqual(self.post("/v1/logs", bomb, {"Content-Encoding": "gzip"}), 413)
        self.assertEqual(self.files(), [])

    def test_bad_gzip_is_400(self):
        self.assertEqual(self.post("/v1/logs", b"not gzip", {"Content-Encoding": "gzip"}), 400)

    def test_bad_content_length_is_400(self):
        for value in ("-5", "abc"):
            c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
            c.putrequest("POST", "/v1/logs")
            c.putheader("Content-Type", "application/json")
            c.putheader("Content-Length", value)
            c.endheaders()
            self.assertEqual(c.getresponse().status, 400)
            c.close()
        self.assertEqual(self.files(), [])

    def test_browser_and_foreign_host_requests_are_403_and_not_written(self):
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE), {"Origin": "https://evil.example"}), 403)
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE), {"Host": "evil.example:4318"}), 403)
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE), {"Host": "localhost:4318"}), 200)
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE), {"Host": "[::1]:4318"}), 200)
        self.assertEqual(len(self.files()[0].read_text().splitlines()), 2)

    def test_non_json_content_type_is_415_and_not_written(self):
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE), {"Content-Type": "text/plain"}), 415)
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE), {"Content-Type": "application/json; charset=utf-8"}), 200)
        self.assertEqual(len(self.files()[0].read_text().splitlines()), 1)

    def test_non_json_is_415(self):
        self.assertEqual(self.post("/v1/logs", b"\x0a\x02\x08\x01"), 415)
        self.assertEqual(self.files(), [])

    def test_unknown_path_is_404(self):
        self.assertEqual(self.post("/v1/other", "{}"), 404)

    def test_query_string_and_trailing_slash_still_route(self):
        self.assertEqual(self.post("/v1/logs?x=1", json.dumps(SAMPLE)), 200)
        self.assertEqual(self.post("/v1/logs/", json.dumps(SAMPLE)), 200)

    def test_truncated_and_multi_member_gzip_are_400(self):
        whole = gzip.compress(json.dumps(SAMPLE).encode())
        self.assertEqual(self.post("/v1/logs", whole[:-6], {"Content-Encoding": "gzip"}), 400)
        self.assertEqual(self.post("/v1/logs", whole + whole, {"Content-Encoding": "gzip"}), 400)
        self.assertEqual(self.post("/v1/logs", whole, {"Content-Encoding": "gzip"}), 200)

    def test_an_unwritable_data_folder_is_a_500(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        self.srv.data_dir = blocker / "otel"  # mkdir under a file raises OSError
        self.assertEqual(self.post("/v1/logs", json.dumps(SAMPLE)), 500)

    def test_bad_port_and_max_body_are_refused(self):
        with self.assertRaises(ValueError):
            r.make_server("127.0.0.1", 70000, self.dir)
        with self.assertRaises(ValueError):
            r.make_server("127.0.0.1", 0, self.dir, max_body=0)

    def test_non_loopback_bind_needs_the_flag(self):
        with self.assertRaisesRegex(ValueError, "--allow-remote"):
            r.make_server("0.0.0.0", 0, self.dir)
        r.make_server("0.0.0.0", 0, self.dir, allow_remote=True).server_close()

    def test_loopback_names(self):
        self.assertTrue(all(map(r.is_loopback, ("127.0.0.1", "::1", "localhost"))))
        self.assertFalse(any(map(r.is_loopback, ("0.0.0.0", "", "10.0.0.5", "example.com"))))


class BadPortEnvTest(unittest.TestCase):
    def run_cli(self, *args):
        root = Path(__file__).resolve().parent.parent
        env = dict(os.environ, TOKSCOPE_PORT="abc")
        return subprocess.run([sys.executable, "-m", "tokscope.cli", *args], cwd=root, env=env, capture_output=True, text=True)

    def test_bad_port_env_does_not_break_other_commands(self):
        p = self.run_cli("--help")
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_bad_port_env_is_a_message_for_the_receiver(self):
        p = self.run_cli("otel-receiver")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("tokscope:", p.stderr)
        self.assertNotIn("Traceback", p.stderr)

    def test_out_of_range_port_flag_is_a_message(self):
        p = self.run_cli("otel-receiver", "--port", "70000")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("tokscope:", p.stderr)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
