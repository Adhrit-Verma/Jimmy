"""One runnable check for stage 4 (the overlay's local API). `python tests/test_stage4.py`."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ambient.api import OverlayAPI  # noqa: E402
from ambient.bus import ContextBus  # noqa: E402
from ambient.db import Store  # noqa: E402


def req(url, token=None, body=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                               method="POST" if body is not None else "GET")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(r, timeout=5)


def make_api():
    calls = []
    state = {"paused": False, "paused_until": 0}

    def pause(m):
        calls.append(("pause", m)); state.update(paused=True, paused_until=1)

    def resume():
        calls.append(("resume",)); state.update(paused=False, paused_until=0)

    api = OverlayAPI({"state": lambda: dict(state), "pause": pause, "resume": resume,
                      "dismiss": lambda i: calls.append(("dismiss", i))}).start()
    return api, calls


def test_local_only_and_token_required():
    api, _ = make_api()
    try:
        assert api.url.startswith("http://127.0.0.1:"), "never reachable off the machine"
        for token in (None, "wrong"):
            try:
                req(f"{api.url}/state", token)
            except urllib.error.HTTPError as e:
                assert e.code == 403
            else:
                raise AssertionError("no token, no access")
        assert json.load(req(f"{api.url}/state", api.token)) == {"paused": False, "paused_until": 0}
    finally:
        api.stop()
    print("ok  127.0.0.1 only, token required")


def test_events_stream_and_actions():
    api, calls = make_api()
    got = []

    def listen():
        with req(f"{api.url}/events", api.token) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    got.append(json.loads(line[6:]))
                    if len(got) >= 3:
                        return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    for _ in range(50):                         # wait for the subscriber to register
        if api._subs:
            break
        time.sleep(0.05)
    api.publish({"type": "card", "id": 7, "kind": "RECALL", "line": "Same x as Tue 15:02", "ts": 1})
    assert json.load(req(f"{api.url}/pause", api.token, {"minutes": 120}))["paused"] is True
    t.join(5)
    try:
        assert got[0]["type"] == "state", "a new overlay gets the current state first"
        assert got[1] == {"type": "card", "id": 7, "kind": "RECALL", "line": "Same x as Tue 15:02", "ts": 1}
        assert got[2]["type"] == "state" and got[2]["paused"] is True, "pausing is broadcast"
        req(f"{api.url}/dismiss", api.token, {"id": 7})
        req(f"{api.url}/toggle-pause", api.token, {})      # paused -> resume
        assert calls == [("pause", 120.0), ("dismiss", 7), ("resume",)], calls
    finally:
        api.stop()
    print("ok  events stream, pause/resume/dismiss")


def test_bus_pause_stops_capture_and_dismiss_quiets_the_gate():
    class FakeGate:
        dismissed_at = None
        def dismissed(self, ts): self.dismissed_at = ts

    b = ContextBus.__new__(ContextBus)
    b.store, b.gate, b._audio, b.paused_until = Store(":memory:"), FakeGate(), None, 0
    b.pause(120)
    assert b.tick() == "paused" and b.overlay_state()["paused"] is True, "a pause captures nothing"
    b.resume()
    assert b.overlay_state() == {"paused": False, "paused_until": 0, "cards": True}
    cid = b.store.add_card("RECALL", "Same x as Tue 15:02", {"e": 1})
    b.dismiss(cid)
    assert b.store.conn.execute("SELECT state FROM cards WHERE id=?", (cid,)).fetchone()[0] == "dismissed"
    assert b.gate.dismissed_at, "a dismissal starts the gate's cooldown"
    print("ok  bus pause and dismiss")


def test_overlay_page_has_no_network():
    root = Path(__file__).resolve().parents[1] / "overlay"
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "connect-src 'none'" in html, "the page itself may not make network requests"
    main = (root / "main.cjs").read_text(encoding="utf-8")
    assert "contextIsolation: true" in main and "nodeIntegration: false" in main and "sandbox: true" in main
    assert "focusable: false" in main and "setIgnoreMouseEvents(true" in main and "skipTaskbar: true" in main
    print("ok  overlay window: isolated, click-through, never takes focus")


def test_effects_never_return_a_value():
    """D26: `useEffect(() => el.scrollIntoView(...))` returned a Promise (this
    Chromium's scrollIntoView does), React called it as the cleanup, and the whole
    overlay went blank on the second answer. Effects must use a braced body."""
    import re
    src = Path(__file__).resolve().parents[1] / "overlay" / "src"
    bad = [f"{p.name}:{n}" for p in src.glob("*.jsx")
           for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
           if re.search(r"useEffect\(\(\)\s*=>\s*[^{\s]", line)]
    assert not bad, f"expression-bodied effects (return values become 'cleanups'): {bad}"
    print("ok  effects have braced bodies")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
