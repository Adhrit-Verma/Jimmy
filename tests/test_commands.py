"""The command matrix (D37): every way of saying each thing, frozen.
`python tests/test_commands.py`. No network.

Three parts: (1) 120+ utterances with the route and command they must reach;
(2) everyday talk that must never trigger anything; (3) a drill that runs each
command through the real Asker and checks the right action ran with the right
arguments. Add a row whenever a real phrasing is missed."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.ask as ask_mod  # noqa: E402
from ambient.db import Store  # noqa: E402

NOW = int(datetime(2026, 10, 2, 15, 0).timestamp() * 1000)

# (what was said, mode, command kind / nav action / None, its argument or None)
MATRIX = [
    # pause / resume
    ("Jimmy pause", "command", "pause", None), ("Jimmy, pause for 20 minutes", "command", "pause", 20.0),
    ("Jimmy pause for an hour", "command", "pause", 60), ("Jimmy pause for half an hour", "command", "pause", 30.0),
    ("Jimmy pause 2h", "command", "pause", 120.0), ("Jimmy stop listening", "command", "pause", None),
    ("Jimmy go private for 2 hours", "command", "pause", 120.0), ("Jimmy resume", "command", "resume", None),
    ("Jimmy start listening again", "command", "resume", None), ("Jimmy unpause", "command", "resume", None),
    # focus
    ("Jimmy focus on the pitch deck", "command", "focus", "the pitch deck"),
    ("Jimmy I need to focus on my thesis", "command", "focus", "my thesis"),
    ("Jimmy set my focus to emails", "command", "focus", "emails"),
    ("Jimmy can you focus on the budget please", "command", "focus", "the budget"),
    ("Jimmy clear my focus", "command", "unfocus", None), ("Jimmy stop focusing", "command", "unfocus", None),
    ("Jimmy stop focusing on Spotify", "command", "unfocus", None),
    ("Jimmy I'm done with the deck", "command", "unfocus", None), ("Jimmy unfocus", "command", "unfocus", None),
    # quiet
    ("Jimmy stop", "command", "hush", None), ("Jimmy never mind", "command", "hush", None),
    ("Jimmy shut up", "command", "hush", None), ("Jimmy be quiet", "command", "hush", None),
    # reminders
    ("Jimmy remind me at 6 to call mom", "command", "remind", None),
    ("Jimmy remind me in 15 minutes to check the oven", "command", "remind", None),
    ("Jimmy remind me tomorrow at 10 to pay rent", "command", "remind", None),
    ("Jimmy remind me to drink water when I open Chrome", "command", "remind", None),
    ("Jimmy could you remind me in 5 minutes to stand up", "command", "remind", None),
    ("Jimmy what are my reminders", "command", "reminders", None),
    ("Jimmy list my reminders", "command", "reminders", None),
    ("Jimmy cancel my reminders", "command", "unremind", None),
    # answers to an offer
    ("Jimmy yes", "command", "yes", None), ("Jimmy yes please", "command", "yes", None),
    ("Jimmy sure", "command", "yes", None), ("Jimmy go ahead", "command", "yes", None),
    ("Jimmy no thanks", "command", "no", None), ("Jimmy not now", "command", "no", None),
    # the curtain
    ("Jimmy curtain", "command", "curtain", None), ("Jimmy privacy mode", "command", "curtain", None),
    ("Jimmy turn on privacy mode", "command", "curtain", None),
    ("Jimmy, turn on privacy curtain.", "command", "curtain", None),
    ("Jimmy enable the privacy curtain", "command", "curtain", None),
    ("Jimmy hide my screen", "command", "curtain", None), ("Jimmy draw the curtain", "command", "curtain", None),
    ("Jimmy lift the curtain", "command", "uncurtain", None), ("Jimmy raise the curtain", "command", "uncurtain", None),
    ("Jimmy turn off privacy mode", "command", "uncurtain", None), ("Jimmy I'm back", "command", "uncurtain", None),
    # pages, views, clutter, copy
    ("Jimmy open that page", "command", "open_url", None), ("Jimmy open the link again", "command", "open_url", None),
    ("Jimmy reopen it", "command", "open_url", None), ("Jimmy open it in the browser", "command", "open_url", None),
    ("Jimmy open the timeline", "command", "open", "timeline"), ("Jimmy show my insights", "command", "open", "insights"),
    ("Jimmy open the dashboard", "command", "open", "dashboard"),
    ("Jimmy close your UI", "command", "close_ui", None), ("Jimmy hide everything", "command", "close_ui", None),
    ("Jimmy clear the screen", "command", "close_ui", None), ("Jimmy close all windows", "command", "close_ui", None),
    ("Jimmy copy the text on my screen", "command", "copy_screen", None),
    ("new copy the text on my screen", "command", "copy_screen", None),
    ("Jimmy copy everything on this page", "command", "copy_screen", None),
    # voice
    ("Jimmy speak softer", "command", "volume", "softer"), ("Jimmy talk louder", "command", "volume", "louder"),
    ("Jimmy turn your voice down", "command", "volume", "softer"), ("Jimmy turn your volume up", "command", "volume", "louder"),
    ("Jimmy lower your voice", "command", "volume", "softer"), ("Jimmy mute your voice", "command", "volume", "mute"),
    ("Jimmy unmute your voice", "command", "volume", "unmute"),
    ("Jimmy stop talking out loud", "command", "volume", "mute"),
    # your face
    ("Jimmy remember my face", "command", "enrol", None), ("Jimmy learn my face", "command", "enrol", None),
    ("Jimmy recognise me", "command", "enrol", None), ("Jimmy set up face recognition", "command", "enrol", None),
    ("Jimmy forget my face", "command", "unenrol", None), ("Jimmy delete my face", "command", "unenrol", None),
    ("Jimmy stop recognizing me", "command", "unenrol", None),
    # moving around Jimmy's own UI
    ("Jimmy next", "nav", "step", None), ("Jimmy go back", "nav", "step", None),
    ("Jimmy previous one", "nav", "step", None), ("Jimmy scroll down", "nav", "scroll", None),
    ("Jimmy scroll up a bit", "nav", "scroll", None), ("Jimmy please scroll down", "nav", "scroll", None),
    ("Jimmy can you scroll up", "nav", "scroll", None),
    ("Hey Jimmy can you scroll down and show me some of the older things I have done that day", "nav", "scroll", None),
    ("Jimmy zoom in", "nav", "zoom", None), ("Jimmy zoom out", "nav", "unzoom", None),
    ("Jimmy close it", "nav", "close", None), ("Jimmy previous day", "nav", "day", None),
    ("Jimmy next day", "nav", "day", None), ("Jimmy the last one", "nav", "edge", None),
    ("Jimmy go to the start", "nav", "edge", None), ("Jimmy only chrome", "nav", "filter", "chrome"),
    ("Jimmy show all apps", "nav", "filter", ""), ("Jimmy search for pricing page", "nav", "q", "pricing page"),
    ("जिमी स्क्रॉल डाउन", "nav", "scroll", None), ("جمی سکرول اپ", "nav", "scroll", None),
    # evidence on show
    ("Jimmy show me the best match", "show", None, None), ("Jimmy open the second one", "show", None, None),
    # your time
    ("Jimmy how was my day", "stats", None, None), ("Jimmy how long was I on youtube today", "stats", None, None),
    ("Jimmy how much time did I spend on Discord yesterday", "stats", None, None),
    ("Jimmy what apps did I use this week", "stats", None, None), ("Jimmy screen time today", "stats", None, None),
    ("Jimmy when did I last use Spotify", "stats", None, None),
    ("Jimmy when did I first open VS Code", "stats", None, None), ("Jimmy my routine this week", "stats", None, None),
    ("Show me the apps I have used today.", "stats", None, None),
    ("Jimmy, can you tell me last time I used Discord?", "stats", None, None),
    # putting things in front of you
    ("Jimmy show me yesterday at 4pm", "goto", None, None), ("Jimmy take me to this morning", "goto", None, None),
    ("Jimmy go to Tuesday", "goto", None, None), ("Jimmy show me the mckinsey form", "recall", None, None),
    # writing
    ("Jimmy draft a reply", "draft", None, None), ("Jimmy write an email saying I'm sick", "draft", None, None),
    ("Jimmy add this to my calendar", "event", None, None), ("Jimmy put this meeting in my calendar", "event", None, None),
    # the screen, the webcam, the past, talk
    ("Jimmy can you see me", "presence", None, None), ("Jimmy can you see my face", "presence", None, None),
    ("Jimmy can you see my screen", "screen", None, None), ("Jimmy what's on my screen", "screen", None, None),
    ("Jimmy summarise this page", "screen", None, None), ("Jimmy what's this", "clarify", None, None),
    ("Jimmy what was on my screen", "clarify", None, None),
    ("Jimmy what did I read yesterday about GCP", "recall", None, None),
    ("Jimmy what was that form on Friday", "recall", None, None),
    ("Jimmy what was I doing an hour ago", "recall", None, None),
    ("Jimmy how does OAuth work", "chat", None, None), ("Jimmy thanks", "chat", None, None),
    ("Jimmy who are you", "chat", None, None), ("Jimmy what can you do", "chat", None, None),
]

# Unknown instructions: these go to the model's tool pick (they start like an instruction).
TO_TOOLS = ["Jimmy turn this off", "Jimmy make it darker", "Jimmy click the login button",
            "Jimmy type my password", "Jimmy close chrome", "Jimmy put the privacy thing over my stuff"]

# Said near the mic without "Jimmy": never navigation, never a command.
TALK = ["I need to stop by the shop", "remember when we went to Goa", "close the deal by Friday",
        "next week we ship", "go back home", "back then it was different", "close enough", "copy that",
        "open the box", "just talking about lunch", "what's next on my list", "the curtain looks nice",
        "pause the video", "I told Jimmy about it", "scroll through instagram later", "done with dinner"]


def heard(text: str) -> str:
    q = ask_mod.parse_wake(ask_mod.normalize(text))
    return ask_mod.normalize(text) if q is None else q


def test_matrix():
    bad = []
    for text, mode, kind, arg in MATRIX:
        q = heard(text)
        got = ask_mod.route(q, now=NOW)[0]
        if got != mode:
            bad.append(f"{text!r}: route {got}, wanted {mode}")
            continue
        if mode == "command" and ask_mod.command(q) != (kind, arg):
            bad.append(f"{text!r}: command {ask_mod.command(q)}, wanted {(kind, arg)}")
        if mode == "nav" and kind:
            ev = ask_mod.nav(q)
            val = ev.get("action") or ("filter" if "filter" in ev else "q")
            if kind in ("filter", "q"):
                if ev.get(kind) != arg:
                    bad.append(f"{text!r}: nav {ev}, wanted {kind}={arg!r}")
            elif val != kind:
                bad.append(f"{text!r}: nav {ev}, wanted {kind}")
    assert not bad, "\n".join(bad)
    print(f"ok  matrix: {len(MATRIX)} utterances reach the right route and arguments")


def test_unknown_instructions_reach_the_tool_pick():
    for text in TO_TOOLS:
        q = heard(text)
        assert ask_mod.route(q, now=NOW)[0] in ("chat", "recall") and ask_mod._ACTIONISH.match(ask_mod.polite(q)), text
    print(f"ok  {len(TO_TOOLS)} unknown instructions go to the model's tool pick")


def test_talk_never_triggers():
    for text in TALK:
        assert ask_mod.nav(text) is None, f"{text!r} navigated"
        assert ask_mod.parse_wake(text) is None, f"{text!r} woke Jimmy"
    a = ask_mod.Asker(Store(":memory:"), lambda e: None)
    a.nav_until = ask_mod.now_ms() + 60_000                     # even inside the navigation window
    assert not any(a.hear(0, "mic", t) for t in TALK), "talk near the mic is not for Jimmy"
    print(f"ok  {len(TALK)} everyday phrases never trigger, even right after an answer")


def test_every_command_runs_its_action():
    """Through the real Asker: the words, the action, its arguments."""
    did, spoken = [], []
    acts = {
        "pause": lambda m: did.append(("pause", m)), "resume": lambda: did.append(("resume",)),
        "focus": lambda t: did.append(("focus", t)), "hush": lambda: did.append(("hush",)),
        "cancel_enrol": lambda: did.append(("cancel_enrol",)), "state": lambda: {},
        "remind": lambda *a: did.append(("remind", *a)), "reminders": lambda: [{"text": "call mom", "due_ts": None, "app": "chrome"}],
        "unremind": lambda: did.append(("unremind",)), "curtain": lambda on: did.append(("curtain", on)),
        "open_file": lambda p: did.append(("file", p)), "volume": lambda w: did.append(("volume", w)) or f"vol {w}",
        "presence": lambda: {"state": "present", "owner": True},
        "enrol": lambda: did.append(("enrol",)) or "Let's do it.", "unenrol": lambda: did.append(("unenrol",)) or "Forgotten.",
    }
    events = []
    ask_mod.now_ms = lambda: NOW
    a = ask_mod.Asker(Store(":memory:"), events.append, speak=spoken.append, actions=acts)
    a.screen_now = lambda: {"frame": {"id": 1, "ts": NOW, "app": "chrome.exe", "title": "Docs"}, "text": "two words"}
    a.last_evidence = [{"ts": NOW - 1000, "url": "https://example.com/x", "thumb": None}]

    def say(text):
        events.clear()
        did.clear()
        a.hear(0, "mic", text)
        assert a.wait_idle(10), text
        return list(did), list(events)

    expect = [
        ("Jimmy pause for 20 minutes", [("pause", 20.0)]), ("Jimmy resume", [("resume",)]),
        ("Jimmy focus on the pitch deck", [("focus", "the pitch deck")]), ("Jimmy clear my focus", [("focus", None)]),
        ("Jimmy stop", [("hush",), ("cancel_enrol",)]), ("Jimmy cancel my reminders", [("unremind",)]),
        ("Jimmy remind me in 15 minutes to check the oven", [("remind", "check the oven", NOW + 15 * 60_000, None)]),
        ("Jimmy remind me to drink water when I open Chrome", [("remind", "drink water", None, "chrome")]),
        ("Jimmy turn on privacy mode", [("curtain", True)]), ("Jimmy lift the curtain", [("curtain", False)]),
        ("Jimmy speak softer", [("volume", "softer")]), ("Jimmy mute your voice", [("volume", "mute")]),
        ("Jimmy remember my face", [("enrol",)]), ("Jimmy forget my face", [("unenrol",)]),
    ]
    for text, want in expect:
        got, _ = say(text)
        assert got == want, f"{text!r}: {got}, wanted {want}"
    _, ev = say("Jimmy what are my reminders")
    assert ev[-1]["text"] == "1 reminder: call mom when you open chrome."
    _, ev = say("Jimmy open that page")
    assert {"type": "open_url", "url": "https://example.com/x"} in ev
    _, ev = say("Jimmy open the timeline")
    assert {"type": "open_view", "view": "timeline", "ts": NOW - 1000} in ev, "opens where we were"
    _, ev = say("Jimmy close your UI")
    assert {"type": "close_all"} in ev
    _, ev = say("Jimmy copy the text on my screen")
    assert {"type": "copy", "text": "two words", "label": "Copied 2 words"} in ev
    _, ev = say("Jimmy can you see me")
    assert ev[-1]["text"] == "Yes, I can see you."
    _, ev = say("Jimmy show me the best match")
    assert ev[0] == {"type": "open_evidence", "index": 0}
    _, ev = say("Jimmy open the fifth one")
    assert ev[-1]["text"] == "There's no such match."
    _, ev = say("Jimmy next")
    assert ev[0] == {"type": "ui", "action": "step", "by": 1} and spoken[-1] != "Next", "navigation is silent"
    _, ev = say("Jimmy show me yesterday at 4pm")
    assert ev[0]["type"] == "open_view" and datetime.fromtimestamp(ev[0]["ts"] / 1000).strftime("%a %H:%M") == "Thu 16:00"
    print(f"ok  drill: {len(expect) + 11} commands ran the right action with the right arguments")


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
