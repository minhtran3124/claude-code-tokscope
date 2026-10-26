"""Minimal OTLP/HTTP-JSON receiver: appends each export request to a daily JSONL file per signal.

core/otel.py reads the api_request events from the logs files into the database."""

import ipaddress
import json
import os
import socket
import sys
import threading
import zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .. import paths

SIGNALS = {"/v1/logs": "logs", "/v1/metrics": "metrics", "/v1/traces": "traces"}
DEFAULT_MAX_BODY = 8 * 1024 * 1024


def default_dir():
    return paths.otel_dir()


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
    if len(out) > limit or d.unconsumed_tail:
        return None
    if not d.eof or d.unused_data:  # cut short, or more than one gzip member
        raise zlib.error("incomplete or multi-member gzip stream")
    return out


def host_name(value):
    """The host part of a Host header (port and IPv6 brackets removed)."""
    value = (value or "").strip()
    if value.startswith("["):
        return value[1:].split("]")[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def read_chunked(rfile, limit):
    """Decode a chunked body, or None when it would pass `limit` bytes. ValueError on bad framing."""
    out, total = [], 0
    while True:
        size = int(rfile.readline(1026).split(b";")[0].strip() or b"x", 16)
        if size < 0:
            raise ValueError("negative chunk size")
        if size == 0:
            while rfile.readline(1026).strip():  # trailers
                pass
            return b"".join(out)
        total += size
        if total > limit:
            return None
        chunk = rfile.read(size)
        if len(chunk) != size or rfile.readline(3).strip():
            raise ValueError("truncated chunk")
        out.append(chunk)


def append_private(data_dir, name, text):
    """Append to a file only the owner reads (POSIX): the bodies can hold prompt text."""
    posix = os.name == "posix"
    data_dir.mkdir(parents=True, exist_ok=True, **({"mode": 0o700} if posix else {}))
    if posix:
        os.chmod(data_dir, 0o700)  # mkdir's mode is masked by the umask and ignored on an existing folder
    fd = os.open(data_dir / name, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if posix:
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a") as f:
            fd = None
            f.write(text)
    finally:
        if fd is not None:
            os.close(fd)


class Server(ThreadingHTTPServer):
    def __init__(self, addr, handler):
        if ":" in addr[0]:
            self.address_family = socket.AF_INET6
        super().__init__(addr, handler)


class Handler(BaseHTTPRequestHandler):
    timeout = 30  # a client that stalls mid-body must not hold a thread for ever

    def do_POST(self):
        signal = SIGNALS.get(urlsplit(self.path).path.rstrip("/"))
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
        limit = self.server.max_body
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            try:
                raw = read_chunked(self.rfile, limit)
            except ValueError:
                self.send_error(400, "bad chunked body")
                return
            if raw is None:
                self.send_error(413, "body too large")
                return
        else:
            try:
                size = int(self.headers.get("Content-Length", ""))
            except ValueError:
                size = -1
            if size < 0:
                self.send_error(400, "bad Content-Length")
                return
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
        except RecursionError:  # nested past the interpreter's limit
            self.send_error(400, "JSON nested too deeply")
            return
        except ValueError:  # bad JSON or bad UTF-8; protobuf lands here, so the exporter must be http/json
            self.send_error(415, "expected OTLP JSON")
            return
        now = datetime.now(timezone.utc)
        data_dir = self.server.data_dir
        try:
            line = json.dumps({"received_at": now.isoformat(), "signal": signal, "body": body})
        except RecursionError:
            self.send_error(400, "JSON nested too deeply")
            return
        try:
            with self.server.write_lock:  # a line over the 8 KiB buffer is several writes; keep parallel requests from interleaving
                append_private(data_dir, f"{signal}-{now:%Y-%m-%d}.jsonl", line + "\n")
        except OSError:  # read-only folder, full disk: tell the exporter, which retries
            self.send_error(500, "cannot write the data folder")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, fmt, *args):
        pass


def make_server(host, port, data_dir, max_body=DEFAULT_MAX_BODY, allow_remote=False):
    if not 0 <= port <= 65535:
        raise ValueError(f"port {port} is outside 0-65535")
    if max_body < 1:
        raise ValueError("--max-body must be at least 1 byte")
    if not allow_remote and not is_loopback(host):
        raise ValueError(f"{host!r} is not a loopback address and the receiver has no authentication; pass --allow-remote to bind it anyway")
    srv = Server((host, port), Handler)
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
