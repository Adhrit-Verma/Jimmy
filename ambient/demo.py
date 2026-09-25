"""`ambient run --demo`: a scripted walkthrough for screen recordings (D28).

Everything runs for real (capture, search, the language model, the voice); only
the *questions* are scripted, fed in as if spoken, with pauses so a recording
reads well. One step per line:

    wait: 3                      pause (seconds)
    card: RECALL | <line>        show a card as the gate would
    say: Jimmy, <question>       as if spoken: the pill listens, then the answer
    reply: <words>               answer Jimmy's own question (no wake word)
    show: <n>                    open evidence n big (0 = best match)
    close                        close it

`--demo path.txt` plays your own script; `#` lines are comments.
"""
from __future__ import annotations

import time

DEFAULT_SCRIPT = """
# 1. A card appears on its own, the way the gate would show one.
wait: 3
card: RECALL | Same McKinsey application as Fri 14:09
wait: 7
# 2. Talk to it.
say: Jimmy, can you hear me?
# 3. Ask about the past, then see the moment big.
say: Jimmy, what was that consulting program application I saw on Friday?
say: Jimmy, show me the best match
wait: 5
close
# 4. A follow-up: it remembers the conversation.
say: Jimmy, and when does it close?
# 5. An unclear question: Jimmy asks back and waits for the answer.
say: Jimmy, what's this?
wait: 2
reply: the one on my screen right now
# 6. What it can do.
say: Jimmy, what can you do?
"""


def parse(script: str) -> list[tuple[str, str]]:
    steps = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cmd, _, arg = line.partition(":")
        steps.append((cmd.strip().lower(), arg.strip()))
    return steps


def run(bus, script: str | None = None) -> None:
    """Drive the live bus through a script. Runs on its own thread."""
    from .db import now_ms

    api, asker = bus._api, bus._asker
    for _ in range(100):                          # wait for the overlay to connect
        if api and api._subs:
            break
        time.sleep(0.2)
    else:
        print("[demo] the overlay never connected; demo skipped")
        return
    print("[demo] starting in 2 s. Start recording now.")
    time.sleep(2)

    def settle(extra: float = 2.5) -> None:
        """Until the answer is done and Jimmy has finished speaking."""
        time.sleep(0.6)
        asker.wait_idle(90)
        time.sleep(0.8)
        end = time.time() + 60
        while getattr(bus, "_speaking", False) and time.time() < end:
            time.sleep(0.2)
        time.sleep(extra)

    card_id = 900_000
    for cmd, arg in parse(script or DEFAULT_SCRIPT):
        if not bus._running:
            return
        print(f"[demo] {cmd}: {arg}")
        if cmd == "wait":
            time.sleep(float(arg or 1))
        elif cmd == "card":
            kind, _, line = arg.partition("|")
            card_id += 1
            api.publish({"type": "card", "id": card_id, "kind": kind.strip().upper() or "RECALL",
                         "line": line.strip(), "ts": now_ms()})
        elif cmd == "say":
            api.publish({"type": "listening"})
            time.sleep(1.4)                       # the pill listens, as if you were speaking
            asker.hear(now_ms(), "mic", arg)
            settle()
        elif cmd == "reply":
            time.sleep(1.2)
            asker.hear(now_ms(), "mic", arg)
            settle()
        elif cmd == "show":
            api.publish({"type": "open_evidence", "index": int(arg or 0)})
        elif cmd == "close":
            api.publish({"type": "close_evidence"})
    print("[demo] done. Jimmy keeps running; Quit from the pill or Ctrl+C.")
