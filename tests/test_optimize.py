import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.experiments import optimize
from tokscope.web import dashboard
from tokscope.core.ingest import connect


class ClaudeLookupTest(unittest.TestCase):
    def test_the_module_keeps_the_claude_lookup_and_the_model_list_and_no_guides(self):
        with mock.patch.dict(os.environ, {"TOKSCOPE_CLAUDE": "/x/claude"}):
            self.assertEqual(optimize._claude(), "/x/claude")
        self.assertIn("sonnet", optimize.MODELS)
        self.assertFalse(hasattr(optimize, "GUIDES"))


class WriteGuardTest(unittest.TestCase):
    """A write to the dashboard needs this origin, the page token and JSON (checked on POST optimize/start)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "h"), "TOKSCOPE_HOME": str(self.tmp / "data")})
        env.start()
        self.addCleanup(env.stop)
        connect(self.tmp / "t.db").close()
        live = dashboard.Live(self.tmp / "t.db", paths.ASSETS / "phases.json", 60, projects_dir=self.tmp)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = dashboard.handler(self.tmp / "t.db", live, self.port, "full", token="tok")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, body, headers):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), method="POST",
                                     headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_write_needs_this_origin_the_page_token_and_json(self):
        body = {"skill": "nope", "budget": 1}
        good = {"Origin": f"http://127.0.0.1:{self.port}", "X-Tokscope-Token": "tok", "Content-Type": "application/json"}
        self.assertEqual(self.post("/optimize/start", body, {**good, "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/optimize/start", body, {k: v for k, v in good.items() if k != "Origin"})[0], 403)
        self.assertEqual(self.post("/optimize/start", body, {**good, "X-Tokscope-Token": "guess"})[0], 403)
        self.assertEqual(self.post("/optimize/start", body, {**good, "Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post("/api/optimize", body, good)[0], 404)   # the guide job route is gone
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/library") as r:
            self.assertIn('<meta name="tokscope-token" content="tok">', r.read().decode())


class DeadCssTest(unittest.TestCase):
    def test_the_deleted_job_page_and_compare_view_leave_no_css_behind(self):
        from tokscope.web.theme.layout import LAYOUT_TOKEN_DASH_CSS
        for dead in ("ol.steps", ".runline", ".cmp .viewbar", ".cmp .path", ".opt .note", ".runbar{", ".runbar i{"):
            self.assertNotIn(dead, LAYOUT_TOKEN_DASH_CSS)


if __name__ == "__main__":
    unittest.main()
