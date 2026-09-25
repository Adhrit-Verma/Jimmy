"""The local API the overlay talks to (Stage 4, D23).

This is the `127.0.0.1` API the spec asked for at Stage 2, deferred until it had
an out-of-process caller (D16): the Electron overlay. Standard library only.

- Bound to 127.0.0.1 on a free port picked by the OS; never reachable off the machine.
- Every request needs `Authorization: Bearer <token>`. The token is random per
  run and reaches Electron only through its environment, never a file.
- Only Electron's main process calls it; the overlay page itself has no network.

Routes: GET /events (Server-Sent Events: state, cards), GET /state,
POST /dismiss {"id"}, POST /pause {"minutes"}, POST /resume, POST /toggle-pause.
"""
from __future__ import annotations

import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


class OverlayAPI:
    def __init__(self, hooks: dict[str, Callable], host: str = "127.0.0.1", port: int = 0):
        self.hooks = hooks                 # dismiss(id), pause(minutes), resume(), state() -> dict
        self.token = secrets.token_urlsafe(24)
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):     # the capture console is for cards, not access logs
                pass

            def _ok(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {api.token}":
                    self.send_error(403)
                    return False
                return True

            def _json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self._ok():
                    return
                if self.path == "/state":
                    return self._json(api.hooks["state"]())
                if self.path != "/events":
                    return self.send_error(404)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q = api.subscribe()
                print("[overlay] connected", flush=True)
                try:
                    api._send(self.wfile, {"type": "state", **api.hooks["state"]()})
                    while True:
                        try:
                            api._send(self.wfile, q.get(timeout=15))
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")   # keep-alive; detects a gone client
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass
                finally:
                    api.unsubscribe(q)

            def do_POST(self):
                if not self._ok():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                except ValueError:
                    return self.send_error(400)
                route = self.path.strip("/")
                if route == "dismiss":
                    api.hooks["dismiss"](int(body.get("id", 0)))
                elif route == "pause":
                    api.hooks["pause"](float(body.get("minutes", 120)))
                elif route == "resume":
                    api.hooks["resume"]()
                elif route == "toggle-pause":
                    st = api.hooks["state"]()
                    api.hooks["resume"]() if st.get("paused") else api.hooks["pause"](120)
                else:
                    return self.send_error(404)
                state = api.hooks["state"]()
                api.publish({"type": "state", **state})
                self._json(state)

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.server.daemon_threads = True
        self.url = f"http://{host}:{self.server.server_address[1]}"

    @staticmethod
    def _send(wfile, event: dict) -> None:
        wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        wfile.flush()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass                        # a stuck overlay must never block capture

    def start(self) -> "OverlayAPI":
        threading.Thread(target=self.server.serve_forever, daemon=True, name="overlay-api").start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
