"""Bounded loopback-only HTTP adapter. Not a production deployment server."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

from .crypto import canonical
from .domain import Service, uid

STATIC = Path(__file__).resolve().parent / "static"
MEDIA = Path(__file__).resolve().parents[1] / "demos"
VIDEO_NAMES = {"patient-sharing.mp4", "physician-access.mp4", "laboratory-provenance.mp4",
               "hospital-affiliation.mp4", "sehataman-complete-walkthrough.mp4"}
MAX_BODY = 65536


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, store, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.service = Service(store, f"http://127.0.0.1:{self.server_port}")
        self.permits = threading.BoundedSemaphore(32)
        self.rate_lock = threading.Lock()
        self.rate = {}

    def process_request(self, request, client_address):
        if not self.permits.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.permits.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.permits.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "SehatAman"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, *_args):
        # Default request-line logging would unnecessarily retain user input.
        pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def send_error(self, code, message=None, explain=None):
        self._send(code, {"error": "http_request", "message": "This request is unavailable."})

    def _send(self, status, body, extra=None):
        extra = extra or {}
        raw = body if isinstance(body, bytes) else canonical(body)
        self.send_response(status)
        headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "private, no-store",
                   "Pragma": "no-cache", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                   "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
                   "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                   "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
                   "Connection": "close", **extra}
        headers["Content-Length"] = str(len(raw))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass
        self.close_connection = True

    def _handle(self):
        request_id = uid()
        try:
            port = self.server.server_port
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1 or hosts[0] not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return self._send(400, {"error": "host", "message": "Use the loopback application address."})
            with self.server.rate_lock:
                minute = int(time.time() // 60)
                key = (self.client_address[0], minute)
                self.server.rate = {k: v for k, v in self.server.rate.items() if k[1] >= minute - 1}
                self.server.rate[key] = self.server.rate.get(key, 0) + 1
                limit = 3000
                if self.server.rate[key] > limit:
                    return self._send(429, {"error": "rate_limit", "message": "Request limit reached. Try again later."}, {"Retry-After": "60"})
            if len(self.path) > 2048:
                return self._send(414, {"error": "request_too_long", "message": "Request is too long."})
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment or parsed.scheme or parsed.netloc:
                return self._send(404, {"error": "unavailable", "message": "This resource is unavailable."})
            path = parsed.path
            if self.command in ("GET", "HEAD") and path.startswith("/demos/") and path[7:] in VIDEO_NAMES:
                video = MEDIA / path[7:]
                if video.is_file():
                    return self._send(200, video.read_bytes(), {"Content-Type": "video/mp4"})
                return self._send(404, {"error": "unavailable", "message": "This recording is not included in this checkout."})
            if self.command in ("GET", "HEAD") and path == "/reviewer":
                return self._send(200, (STATIC / "reviewer.html").read_bytes(), {"Content-Type": "text/html; charset=utf-8"})
            if self.command in ("GET", "HEAD") and path in ("/", "/app.js", "/style.css", "/brand.svg"):
                name, mime = {"/": ("index.html", "text/html; charset=utf-8"),
                              "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                              "/style.css": ("style.css", "text/css; charset=utf-8"),
                              "/brand.svg": ("brand.svg", "image/svg+xml")}[path]
                return self._send(200, (STATIC / name).read_bytes(), {"Content-Type": mime})
            if not path.startswith("/api/") or self.command == "HEAD":
                return self._send(404, {"error": "unavailable", "message": "This resource is unavailable."})
            body = {}
            if self.command not in ("GET", "HEAD"):
                if self.headers.get_all("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                    return self._send(400, {"error": "framing", "message": "A bounded request body is required."})
                try:
                    length = int(self.headers["Content-Length"])
                except (TypeError, ValueError):
                    return self._send(400, {"error": "framing", "message": "Invalid request length."})
                if not 0 <= length <= MAX_BODY:
                    return self._send(413, {"error": "body_limit", "message": "Request exceeds the 64 KiB local limit."})
                if self.headers.get_content_type() != "application/json":
                    return self._send(415, {"error": "content_type", "message": "Use structured JSON input."})
                if self.headers.get_all("Origin", []) != ["http://" + hosts[0]]:
                    return self._send(403, {"error": "origin", "message": "Use the local application to make changes."})
                raw = self.rfile.read(length)
                if len(raw) != length:
                    return self._send(400, {"error": "framing", "message": "Incomplete request body."})
                try:
                    body = json.loads(raw, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(body, dict):
                        raise ValueError()
                except (ValueError, UnicodeDecodeError, RecursionError):
                    return self._send(422, {"error": "invalid_json", "message": "Use a valid JSON object."})
            reply = self.server.service.handle(self.command, path, dict(self.headers.items()), body, request_id)
            self._send(reply.status, reply.body, {"X-Request-ID": request_id, **reply.headers})
        except (socket.timeout, ConnectionError):
            self.close_connection = True
        except Exception:
            # No request body, credentials, CNIC, clinical content or trace is logged.
            self._send(500, {"error": "internal", "message": "The local request could not complete. No clinical payload is included."},
                       {"X-Request-ID": request_id})
