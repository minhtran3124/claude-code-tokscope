"""Minimal OTLP/HTTP-JSON receiver: appends each export request to a daily JSONL file per signal.

It only collects data: no view reads data/otel yet (issue #58)."""

import ipaddress
import json
import os
import sys
import threading
import zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import paths

SIGNALS = {"/v1/logs": "logs", "/v1/metrics": "metrics", "/v1/traces": "traces"}
DEFAULT_MAX_BODY = 8 * 1024 * 1024


def default_dir():
    return Path(os.environ.get("TOKSCOPE_DATA_DIR") or paths.home() / "data" / "otel")


def is_loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def unzip(raw, limit):
    """Decompress gzip, or None when the result would pass `limit` bytes (a gzip bomb)."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(raw, limit + 1)
    return None if len(out) > limit or d.unconsumed_tail else out


def host_name(value):
    """The host part of a Host header (port and IPv6 brackets removed)."""
    value = (value or "").strip()
    if value.startswith("["):
        return value[1:].split("]")[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        signal = SIGNALS.get(self.path)
        if signal is None:
            self.send_error(404)
            return
        # Browsers (CORS "simple" POSTs) and DNS rebinding can reach a loopback port; exporters send neither header.
        if self.headers.get("Origin") is not None or (not self.server.allow_remote and not is_loopback(host_name(self.headers.get("Host")))):
            self.send_error(403, "browser or non-loopback request")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.send_error(415, "expected Content-Type application/json")
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            size = -1
        if size < 0:
            self.send_error(400, "bad Content-Length")
            return
        limit = self.server.max_body
        if size > limit:
            self.send_error(413, "body too large")
            return
        raw = self.rfile.read(size)
        if self.headers.get("Content-Encoding") == "gzip":
            try:
                raw = unzip(raw, limit)
            except zlib.error:
                self.send_error(400, "bad gzip body")
                return
            if raw is None:
                self.send_error(413, "decompressed body too large")
                return
        try:
            body = json.loads(raw)
        except ValueError:  # bad JSON or bad UTF-8; protobuf lands here, so the exporter must be http/json
            self.send_error(415, "expected OTLP JSON")
            return
        now = datetime.now(timezone.utc)
        data_dir = self.server.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"received_at": now.isoformat(), "signal": signal, "body": body})
        with self.server.write_lock:  # a line over the 8 KiB buffer is several writes; keep parallel requests from interleaving
            with open(data_dir / f"{signal}-{now:%Y-%m-%d}.jsonl", "a") as f:
                f.write(line + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, fmt, *args):
        pass


def make_server(host, port, data_dir, max_body=DEFAULT_MAX_BODY, allow_remote=False):
    if not allow_remote and not is_loopback(host):
        raise ValueError(f"{host!r} is not a loopback address and the receiver has no authentication; pass --allow-remote to bind it anyway")
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.write_lock = threading.Lock()
    srv.data_dir, srv.max_body, srv.allow_remote = Path(data_dir), max_body, allow_remote
    return srv


def serve(host, port, data_dir, max_body=DEFAULT_MAX_BODY, allow_remote=False):
    srv = make_server(host, port, data_dir, max_body, allow_remote)
    print(f"tokscope receiver on http://{host}:{srv.server_address[1]} -> {data_dir}", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
