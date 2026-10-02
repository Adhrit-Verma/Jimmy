"""One runnable check for D31 (insights, commands, usage answers, time phrases).
`python tests/test_stage6.py`. No network, no Electron, no capture devices."""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.ask as ask_mod  # noqa: E402
from ambient import insights  # noqa: E402
from ambient.db import Store  # noqa: E402
from ambient.plugin import time_window  # noqa: E402

MIN = 60_000
T0 = int(datetime(2026, 10, 2, 9, 0).timestamp() * 1000)   # a Friday, 09:00 local


def day_store() -> Store:
    s = Store(":memory:")
    w = s.open_window(ts=T0)
    for i, (app, title) in enumerate([("chrome.exe", "YouTube - Chrome")] * 10 + [("Discord.exe", "general")] * 5):
        s.add_frame(w, app, title, ts=T0 + i * MIN)
    s.add_frame(w, "Code.exe", "main.py", ts=T0 + 60 * MIN)          # 45 min after Discord: away
    s.add_audio(T0 + MIN, T0 + MIN + 4000, "mic", "hello there")
    s.add_audio(T0 + 2 * MIN, T0 + 2 * MIN + 1000, "command", "Jimmy pause")
    return s


def test_usage_estimate_caps_gaps_and_splits_hours():
    s = day_store()
    d = insights.day(s, "2026-10-02", now=T0 + 61 * MIN)
    apps = {a["app"]: a["ms"] for a in d["apps"]}
    assert apps == {"Chrome": 10 * MIN, "Discord": 9 * MIN, "VS Code": MIN}, apps
    # Discord's last frame counts 5 min (the cap), not the 46 min until VS Code.
    assert d["active_ms"] == 20 * MIN and d["switches"] == 2
    assert d["longest"]["app"] == "Chrome" and d["longest"]["ms"] == 10 * MIN
    assert sum(sum(h.values()) for h in d["hours"]) == d["active_ms"], "hours add up to the day"
    assert d["speech"] == {"segments": 1, "ms": 4000} and d["commands"] == 1
    assert len(d["week"]) == 7 and d["week"][-1]["day"] == "2026-10-02"
    print("ok  insights: capped gaps, runs, hours, week, tallies")


def test_usage_answers_are_one_line():
    s = day_store()
    w = (T0, T0 + 61 * MIN, "today")
    line, data = insights.answer(s, "how long was I on youtube today", w, T0 + 61 * MIN)
    assert line == "10 minutes on YouTube today, of 20 minutes on screen.", line
    line, _ = insights.answer(s, "how was my day", w, T0 + 61 * MIN)
    assert line == "20 minutes on screen today. Most on Chrome (10 minutes), then Discord (9 minutes).", line
    assert insights.answer(s, "how long on slack", w, T0)[0] == "I didn't see Slack today."
    assert insights.answer(Store(":memory:"), "screen time", w, T0)[0] == "Nothing captured today."
    assert insights.app_name("C:/Program Files/Microsoft VS Code/Code.exe") == "VS Code"
    print("ok  usage answers: one short line")


def test_router_commands_and_stats():
    route, command = ask_mod.route, ask_mod.command
    for text, want in (("pause", ("pause", None)), ("pause for 30 minutes", ("pause", 30.0)),
                       ("pause for half an hour", ("pause", 30.0)), ("pause 2h", ("pause", 120.0)),
                       ("stop listening", ("pause", None)), ("resume", ("resume", None)),
                       ("focus on finishing the resume", ("focus", "finishing the resume")),
                       ("I want to focus on the deck.", ("focus", "the deck")),
                       ("clear my focus", ("unfocus", None)), ("stop", ("hush", None)),
                       ("never mind", ("hush", None)), ("open the timeline", ("open", "timeline")),
                       ("show my insights", ("open", "insights"))):
        assert command(text) == want, f"{text!r} -> {command(text)}, wanted {want}"
    for text in ("what should I focus on", "stop the video I was watching yesterday",
                 "how do I pause a video", "show me the best match"):
        assert command(text) is None, f"{text!r} is not a command"
    for text, mode in (("how long was I on chrome today", "stats"), ("how was my day", "stats"),
                       ("what apps did I use yesterday", "stats"), ("screen time this week", "stats"),
                       ("how much time did I spend on YouTube", "stats"),
                       ("how long ago did I see the form", "recall"),
                       ("how long does the application take", "chat"),
                       ("which app had the mckinsey form", "recall"), ("pause for 10 minutes", "command")):
        assert route(text, now=T0)[0] == mode, f"{text!r} -> {route(text, now=T0)[0]}, wanted {mode}"
    last = {"mode": "stats", "query": "how long on chrome", "ts": T0 - 30_000, "term": "chrome", "when": "today"}
    assert route("and yesterday?", last, T0) == ("stats", "and yesterday? chrome")
    assert route("what about discord?", last, T0) == ("stats", "what about discord? today")
    print("ok  router: commands, usage questions, usage follow-ups")


def test_time_phrases():
    now = T0 + 3 * 3600_000                                            # Friday 12:00
    since, until, label = time_window("what was I doing an hour ago", now)
    assert since < now - 3600_000 < until <= now and label == "an hour ago"
    since, until, _ = time_window("2 days ago", now)
    assert datetime.fromtimestamp(since / 1000).strftime("%a %H:%M") == "Wed 00:00"
    since, _, label = time_window("last friday", now)
    assert label == "Friday" and (now - since) > 6 * 86_400_000, "last Friday on a Friday is a week back"
    since, _, _ = time_window("friday", now)
    assert datetime.fromtimestamp(since / 1000).date() == datetime.fromtimestamp(now / 1000).date()
    assert time_window("this month", now)[2] == "last 30 days"
    print("ok  time phrases: ago, last <weekday>, month")


def test_asker_commands_stats_and_clarify_reset():
    events, spoken, did = [], [], []
    state = {"paused": False}
    acts = {"pause": lambda m: did.append(("pause", m)), "resume": lambda: did.append(("resume",)),
            "focus": lambda t: did.append(("focus", t)), "hush": lambda: did.append(("hush",)),
            "state": lambda: dict(state)}
    ask_mod.now_ms = lambda: T0 + 61 * MIN
    a = ask_mod.Asker(day_store(), events.append, speak=spoken.append, actions=acts)

    def turn(fn):
        events.clear()
        fn()
        assert a.wait_idle(10)
        return events

    ev = turn(lambda: a.hear(0, "mic", "Jimmy, pause for 30 minutes"))
    assert did[-1] == ("pause", 30.0) and spoken[-1] == "Paused for 30 minutes."
    assert [e["type"] for e in ev] == ["state", "toast"], "a command is a toast, not an answer panel"
    turn(lambda: a.hear(0, "mic", "Jimmy, stop"))                   # one word, still a command
    assert did[-1] == ("hush",) and any(e["type"] == "answer_close" for e in events)
    turn(lambda: a.ask("focus on the quarterly deck"))
    assert did[-1] == ("focus", "the quarterly deck")

    ev = turn(lambda: a.hear(0, "mic", "Jimmy, how long was I on youtube today"))
    got = next(e for e in ev if e["type"] == "answer_evidence")
    assert got["mode"] == "stats" and got["stats"]["match"]["ms"] == 10 * MIN
    assert next(e for e in ev if e["type"] == "answer_end")["text"].startswith("10 minutes on YouTube")

    a.pending = {"q": "old", "asked": 1, "ts": 0}                   # left over from long ago
    turn(lambda: a.ask("what is this"))
    assert a.pending["asked"] == 1, "a new unclear question starts its own count"
    turn(lambda: a.ask("how was my day"))
    assert a.pending is None, "any other question drops the question Jimmy asked back"
    print("ok  asker: commands, usage answers, clarify count resets")


def test_small_thumbs():
    import tempfile

    import cv2

    from ambient import recall
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "big.jpg"
        cv2.imwrite(str(p), np.full((720, 1280, 3), 120, np.uint8))
        small = cv2.imdecode(np.frombuffer(recall._small(str(p), 240), np.uint8), cv2.IMREAD_COLOR)
        assert small.shape[1] == 240 and small.shape[0] == 135
        p2 = Path(d) / "junk.jpg"
        p2.write_bytes(b"\xff\xd8jpeg")
        assert recall._small(str(p2), 240) == b"\xff\xd8jpeg", "undecodable: served as-is"
    print("ok  small thumbnails for the strip")


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
