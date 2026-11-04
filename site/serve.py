"""Serve the website from an existing Render *web* service (Python), without the desktop app.

The site is static (render.yaml publishes it as a static site). This is for a Render
service that was created as a Python web service and has to be kept (its URL or
settings matter): set its Build Command to `echo "no build"` and its Start Command to
`python site/serve.py`. Standard library only, so nothing from requirements.txt (the
Windows desktop app) is installed. It sends the same security headers as render.yaml.

Locally: `python site/serve.py`, then open http://127.0.0.1:8000.
"""
from __future__ import annotations

import functools
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEADERS = {   # keep in step with render.yaml
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": ("default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline' "
                                "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                                "script-src 'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
                                "frame-ancestors 'none'"),
}


class Site(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        for name, value in HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def send_head(self):
        if self.path.split("?", 1)[0].endswith(".py"):
            self.send_error(404)            # the server itself isn't part of the site
            return None
        return super().send_head()


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))       # Render sets PORT
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    server = ThreadingHTTPServer((host, port), functools.partial(Site, directory=str(ROOT)))
    print(f"serving {ROOT} on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
