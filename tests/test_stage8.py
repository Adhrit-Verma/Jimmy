"""One runnable check for D35: what the first real session got wrong.
`python tests/test_stage8.py`. No network, no webcam, no Electron.

The routing cases are the human's actual words from 2026-10-02 (14:12-15:51),
including Whisper's spellings, each of which went to the wrong place that day."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.ask as ask_mod  # noqa: E402
from ambient import insights  # noqa: E402
from ambient.db import Store  # noqa: E402
from jimmy.memory import Memory  # noqa: E402

MIN = 60_000
NOW = int(datetime(2026, 10, 2, 15, 0).timestamp() * 1000)


def heard(text: str) -> str:
    """What the Asker routes, from what Whisper wrote."""
    q = ask_mod.parse_wake(ask_mod.normalize(text))
    return ask_mod.normalize(text) if q is None else q


def test_real_session_routes():
    route = lambda t: ask_mod.route(heard(t), now=NOW)[0]  # noqa: E731
    for text, mode in (
            ("Jimmy, turn on privacy curtain.", "command"),          # was: "I don't have the ability"
            ("Jimmy close your UI", "command"),                      # was: "I don't have a UI to close"
            ("stop focusing on Spotify", "command"),                 # was: an answer about apps
            ("new copy the text on my screen", "command"),           # was: read the text out
            ("Jimmy can you see my face?", "presence"),              # was: "I can't see you"
            ("Jimmy can you see my screen?", "screen"),              # was: "No, I can't see your screen"
            ("Show me the apps I have used today.", "stats"),
            ("Jimmy can you tell me what was the apps I have opened last month?", "stats"),
            ("Tell me about my routine last month.", "stats"),
            ("Jimmy, can you tell me last time I used Discord?", "stats"),   # was: answered from its own command
            ("Hey Jimmy can you scroll down and show me some of the older things I have done that day", "nav"),
            ("جمی سکرول اپ", "nav"),                                 # "Jimmy scroll up", in Urdu script
            ("Pause for 30 minutes.", "command"), ("Focus on Spotify", "command"),
            ("what's on my screen", "screen"), ("how are you", "chat"),
    ):
        assert route(text) == mode, f"{text!r} -> {route(text)}, wanted {mode}"
    assert ask_mod.parse_wake("जिमी स्क्रॉल डाउन") == "स्क्रॉल डाउन" and heard("जिमी स्क्रॉल डाउन") == "scroll down"
    assert ask_mod.nav("can you scroll down please") == {"type": "ui", "action": "scroll", "dir": "down"}
    for talk in ("I told Jimmy about it", "just talking about lunch", "which app had the mckinsey form"):
        assert route(talk) != "command" and route(talk) != "nav", talk
    print("ok  the first session's misses now route where they should")


def test_usage_last_first_routine():
    s = Store(":memory:")
    w = s.open_window(ts=1)
    tue = int(datetime(2026, 9, 22, 14, 58).timestamp() * 1000)
    for i in range(5):
        s.add_frame(w, "Discord.exe", "#general", ts=tue + i * MIN)
    for i in range(30):
        s.add_frame(w, "Code.exe", "main.py", ts=NOW - 40 * MIN + i * MIN)
    s.add_frame(w, "Discord.exe", "#general", ts=NOW - 5 * MIN)
    ans = lambda q, w=None: insights.answer(s, q, w, NOW)[0]  # noqa: E731
    assert ans("last time I used Discord") == "Discord: last seen today at 14:55."
    assert ans("when did I start using Discord") == "Discord: first seen Tue 22 Sep at 14:58."
    thu = (int(datetime(2026, 10, 1).timestamp() * 1000), int(datetime(2026, 10, 2).timestamp() * 1000), "Thursday")
    assert ans("when did I start using Discord", thu) == "Not on Thursday. Discord: first seen Tue 22 Sep at 14:58."
    assert ans("my routine").startswith("1 active day in the last 30 days, about 39 minutes a day, usually from 14:20.")
    print("ok  usage: last seen, first seen (falling back to all history), routine")


class FakeLLM:
    configured = True

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def chat(self, msgs, **kw):
        self.calls += 1
        return self.reply


class FakeJimmy:
    def __init__(self, reply):
        self.llm = FakeLLM(reply)

    def ask_stream(self, q, session, snippets, instructions):
        yield "Do you mean the form on Friday, or the one on Tuesday?"


def asker(reply, **acts):
    events, spoken = [], []
    ask_mod.now_ms = lambda: NOW
    a = ask_mod.Asker(Store(":memory:"), events.append, speak=spoken.append, jimmy=FakeJimmy(reply),
                      actions={"state": lambda: {}, **acts})

    def turn(fn):
        events.clear()
        fn()
        assert a.wait_idle(10)
        return list(events)
    return a, turn, spoken


def test_model_picks_a_tool_or_says_why_not():
    did = []
    a, turn, spoken = asker('{"tool": "curtain", "args": {"on": true}}', curtain=lambda on: did.append(on))
    turn(lambda: a.hear(0, "mic", "Jimmy, put the privacy thing over my stuff"))
    assert did == [True] and spoken[-1] == "Curtain down.", "an unknown phrasing still reaches the tool"

    a, turn, spoken = asker('{"tool": "cannot", "args": {"reason": "I read text, not formatting like bold."}}')
    ev = turn(lambda: a.hear(0, "mic", "Jimmy, copy only bold letters"))
    end = next(e for e in ev if e["type"] == "answer_end")
    assert end["text"] == "I read text, not formatting like bold.", end

    a, turn, spoken = asker('{"tool": "ask_back", "args": {"question": "Turn off the curtain, or my voice?"}}')
    ev = turn(lambda: a.hear(0, "mic", "Jimmy, turn this off"))
    assert next(e for e in ev if e["type"] == "answer_end")["awaiting"] and a.listen_until > NOW
    assert ev[-1] == {"type": "listening", "prompt": "listening… your answer"}

    a, turn, _ = asker('{"tool": "answer", "args": {}}')
    ev = turn(lambda: a.ask("what was the form on friday"))
    assert a._jimmy.llm.calls == 0, "questions don't pay for a tool pick"
    print("ok  tools: the model maps phrasing to Jimmy's tools, says why not, or asks back")


def test_answers_that_ask_back_keep_listening():
    a, turn, _ = asker("")
    w = a.store.open_window(ts=NOW - 60 * MIN)
    for i, title in enumerate(("Acme application form", "Beta application form")):
        f = a.store.add_frame(w, "chrome.exe", title, ts=NOW - (60 - i) * MIN)
        a.store.add_text(f, "uia", f"{title}\nApplications close soon")
    ev = turn(lambda: a.ask("the application form"))
    end = next(e for e in ev if e["type"] == "answer_end")
    assert end["awaiting"] and a.listen_until > NOW, "Jimmy asked which one: the reply needs no wake word"
    print("ok  an answer that asks back keeps listening")


def test_commands_close_copy_volume_presence():
    mem = Memory(":memory:")
    a, turn, spoken = asker("", volume=lambda w: f"vol {w}", presence=lambda: {"state": "present"})
    a.screen_now = lambda: {"frame": {"id": 1, "ts": NOW, "app": "WINWORD.EXE", "title": "Resume"},
                            "text": "Adhrit Resume\nSkills Python"}
    ev = turn(lambda: a.hear(0, "mic", "Jimmy, close your UI"))
    assert {"type": "close_all"} in ev
    ev = turn(lambda: a.hear(0, "mic", "Jimmy copy the text on my screen"))
    assert {"type": "copy", "text": "Adhrit Resume\nSkills Python", "label": "Copied 4 words"} in ev
    turn(lambda: a.hear(0, "mic", "Jimmy, speak softer"))
    assert spoken[-1] == "vol softer"
    turn(lambda: a.hear(0, "mic", "Jimmy, can you see me?"))
    assert spoken[-1].startswith("Yes, one face at the screen. I count faces; I don't recognise them")
    mem.set_setting("voice_volume", 35)
    mem.set_setting("voice_volume", 45)
    assert mem.setting("voice_volume") == "45" and mem.setting("nope", "x") == "x"
    print("ok  close everything, copy the screen, volume remembered, 'can you see me' from presence")


def test_one_instance_only():
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    first = k32.CreateMutexW(None, False, "Local\\JimmyAmbientRunTest")
    assert first and ctypes.get_last_error() != 183
    second = k32.CreateMutexW(None, False, "Local\\JimmyAmbientRunTest")
    assert ctypes.get_last_error() == 183, "a second run sees the first"
    k32.CloseHandle(second)
    k32.CloseHandle(first)
    src = (Path(__file__).resolve().parents[1] / "ambient" / "__main__.py").read_text(encoding="utf-8")
    assert "JimmyAmbientRun" in src, "ambient run takes the lock"
    print("ok  one Jimmy at a time")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
