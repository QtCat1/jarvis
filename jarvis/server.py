"""Tiny web server: serves the HUD and exposes POST /api/ask.

Default: localhost only (this computer).
--lan:   also reachable from your phone on the same Wi-Fi, protected by a PIN.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .brain import Jarvis

HUD = Path(__file__).parent / "hud.html"
_lock = threading.Lock()
_jarvis = Jarvis()
PIN: str | None = None  # set when running with --lan
COOKIE = "jarvis_pin"
_last_request = 0.0
UPDATE_EVERY = float(os.environ.get("JARVIS_UPDATE_HOURS", "6")) * 3600


def _auto_update_loop() -> None:
    """While the HUD runs, look for updates every few hours and restart when idle."""
    from . import update as u

    while True:
        time.sleep(UPDATE_EVERY)
        if not u.auto_enabled():
            continue
        while time.time() - _last_request < 120:  # never restart mid-conversation
            time.sleep(30)
        if u.apply_update(log=lambda m: None, timeout=30) == "updated":
            u.schedule_restart(0.5)


def _stable_pin() -> str:
    """Same PIN every start (kept in your home folder) so the phone stays unlocked after auto-updates."""
    f = Path.home() / ".jarvis_pin"
    try:
        p = f.read_text().strip()
        if len(p) == 6 and p.isdigit():
            return p
    except OSError:
        pass
    p = "".join(secrets.choice("0123456789") for _ in range(6))
    try:
        f.write_text(p)
    except OSError:
        pass
    return p


def lan_ip() -> str:
    """Best-effort local network address of this computer."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no traffic is sent
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _cookie_ok(self) -> bool:
        if PIN is None:
            return True
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return COOKIE in c and secrets.compare_digest(c[COOKIE].value, PIN)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            given = parse_qs(url.query).get("pin", [""])[0]
            headers = {}
            if PIN is not None and not self._cookie_ok():
                if not secrets.compare_digest(given, PIN):
                    return self._send(
                        401,
                        b"<h2 style='font-family:sans-serif'>Jarvis is locked. "
                        b"Open the full link shown on your computer (it ends with ?pin=...).</h2>",
                        "text/html; charset=utf-8",
                    )
                headers["Set-Cookie"] = f"{COOKIE}={PIN}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict"
            self._send(200, HUD.read_bytes(), "text/html; charset=utf-8", headers)
        elif url.path == "/api/status":
            if not self._cookie_ok():
                return self._send(401, b"{}", "application/json")
            self._send(200, json.dumps({"mode": _jarvis.mode}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/ask":
            return self._send(404, b"not found", "text/plain")
        if not self._cookie_ok():
            return self._send(401, b'{"error":"locked"}', "application/json")
        try:
            n = int(self.headers.get("Content-Length", 0))
            message = json.loads(self.rfile.read(n) or b"{}").get("message", "")
        except Exception:
            return self._send(400, b'{"error":"bad request"}', "application/json")
        global _last_request
        _last_request = time.time()
        with _lock:
            reply = _jarvis.ask(str(message)[:2000])
        self._send(200, json.dumps({"reply": reply, "mode": _jarvis.mode}).encode(), "application/json")

    def log_message(self, *args) -> None:  # keep the console clean
        pass


def serve(port: int = 8765, lan: bool = False) -> None:
    global PIN
    host = "0.0.0.0" if lan else "127.0.0.1"
    if lan:
        PIN = _stable_pin()
    srv = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=_auto_update_loop, daemon=True).start()
    print(f"\nJarvis HUD  (mode: {_jarvis.mode})   Ctrl+C to stop")
    print(f"  On this computer:  http://127.0.0.1:{port}")
    if lan:
        print(f"  On your phone:     http://{lan_ip()}:{port}/?pin={PIN}")
        print("  (phone must be on the same Wi-Fi; if Windows asks, allow access on Private networks)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    serve()
