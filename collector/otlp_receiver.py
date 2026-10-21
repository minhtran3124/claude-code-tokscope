"""Minimal OTLP/HTTP-JSON receiver: appends each export request to a daily JSONL file per signal."""

import gzip
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DATA_DIR = Path(os.environ.get("TOKSCOPE_DATA_DIR", Path(__file__).resolve().parent.parent / "data" / "otel"))
HOST = os.environ.get("TOKSCOPE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TOKSCOPE_PORT", "4318"))
SIGNALS = {"/v1/logs": "logs", "/v1/metrics": "metrics", "/v1/traces": "traces"}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        signal = SIGNALS.get(self.path)
        if signal is None:
            self.send_error(404)
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            # protobuf would land here; the exporter must be set to http/json
            self.send_error(415, "expected OTLP JSON")
            return
        now = datetime.now(timezone.utc)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"received_at": now.isoformat(), "signal": signal, "body": body})
        with open(DATA_DIR / f"{signal}-{now:%Y-%m-%d}.jsonl", "a") as f:
            f.write(line + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"tokscope receiver on http://{HOST}:{PORT} -> {DATA_DIR}", file=sys.stderr)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
