"""One runnable check for D32-D34 (Jimmy on its own, hands-free UI, privacy curtain).
`python tests/test_stage7.py`. No network, no webcam, no Electron."""
from __future__ import annotations

import pickle
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.ask as ask_mod  # noqa: E402
from ambient import config, proactive  # noqa: E402
from ambient.db import Store  # noqa: E402
from jimmy.memory import Memory  # noqa: E402

MIN = 60_000
FRI = datetime(2026, 10, 2, 12, 0)            # Friday noon, local
NOW = int(FRI.timestamp() * 1000)


def test_navigation_phrases():
    nav = ask_mod.nav
    for text, want in (("next", {"action": "step", "by": 1}), ("go back", {"action": "step", "by": -1}),
                       ("scroll down", {"action": "scroll", "dir": "down"}), ("Scroll up a bit.", {"action": "scroll", "dir": "up"}),
                       ("close it", {"action": "close"}), ("zoom in", {"action": "zoom"}),
                       ("previous day", {"action": "day", "by": -1}), ("the last one", {"action": "edge", "to": "last"})):
        got = nav(text)
        assert got and got["type"] == "ui" and {k: got[k] for k in want} == want, (text, got)
    assert nav("only chrome") == {"type": "open_view", "view": "timeline", "filter": "chrome"}
    assert nav("search for pricing page")["q"] == "pricing page"
    for talk in ("just talking about lunch", "what's next on my list", "next week we ship", "close the deal by friday"):
        assert nav(talk) is None, f"{talk!r} is talk, not navigation"
    print("ok  navigation phrases, and talk that isn't")


def test_router_new_modes():
    route, command = ask_mod.route, ask_mod.command
    for text, mode in (("show me yesterday at 3pm", "goto"), ("take me to this morning", "goto"),
                       ("show me the mckinsey form", "recall"), ("draft a reply to this", "draft"),
                       ("write a short email saying I'll be late", "draft"),
                       ("add this to my calendar", "event"), ("remind me at 5 to call Sam", "command"),
                       ("next", "nav"), ("what are my reminders", "command"), ("yes", "command"),
                       ("curtain", "command"), ("lift the curtain", "command"), ("open that page", "command")):
        assert route(text, now=NOW)[0] == mode, f"{text!r} -> {route(text, now=NOW)[0]}, wanted {mode}"
    assert command("open it") is None and route("open it", now=NOW)[0] == "nav", "'open it' zooms, it doesn't browse"
    assert command("raise the curtain")[0] == "uncurtain" and command("draw the curtain")[0] == "curtain"
    print("ok  router: goto, draft, event, reminders, yes, curtain, open page")


def test_reminder_parsing():
    pr = proactive.parse_reminder
    what, due, app = pr("remind me at 5 to call Sam", NOW)
    assert (what, app) == ("call Sam", None) and datetime.fromtimestamp(due / 1000).strftime("%a %H:%M") == "Fri 17:00"
    what, due, _ = pr("remind me to stretch in 20 minutes", NOW)
    assert what == "stretch" and due == NOW + 20 * MIN
    what, due, _ = pr("remind me tomorrow at 9 to send the deck", NOW)
    assert what == "send the deck" and datetime.fromtimestamp(due / 1000).strftime("%a %H:%M") == "Sat 09:00"
    what, due, app = pr("remind me to drink water when I open Discord", NOW)
    assert (what, due, app) == ("drink water", None, "discord")
    _, due, _ = pr("remind me at 11 to stand up", NOW)                 # 11:00 has passed at noon
    assert datetime.fromtimestamp(due / 1000).strftime("%a %H:%M") == "Sat 11:00"
    assert pr("remind me to call mum", NOW)[1:] == (None, None), "no when: Jimmy asks for one"

    m = Memory(":memory:")
    m.add_reminder("call Sam", NOW + MIN)
    m.add_reminder("drink water", app="discord")
    assert not m.due_reminders(NOW, "chrome youtube")
    assert [r["text"] for r in m.due_reminders(NOW, "discord #general")] == ["drink water"]
    assert [r["text"] for r in m.due_reminders(NOW + 2 * MIN, None)] == ["call Sam"]
    m.set_reminder_state(None, "cancelled")
    assert m.reminders() == []
    print("ok  reminders: at, in, tomorrow, when I open, due by time or app")


def test_deadlines():
    seen = NOW
    for text, due_day in (("Applications close on Monday", "Mon 05"), ("Submit by 9 October", "Fri 09"),
                          ("Interview tomorrow at 3pm", "Sat 03"), ("Due Oct 14, 2026", "Wed 14")):
        got = proactive.parse_due(text, seen)
        assert got and datetime.fromtimestamp(got[0] / 1000).strftime("%a %d") == due_day, (text, got)
    assert proactive.parse_due("Posted on 3 March 2025", seen) is None, "the past is not a deadline"
    assert proactive.parse_due("Launch on 1 March 2027", seen) is None, "too far out for a card"
    got = proactive.parse_due("Applications close on Monday", seen)
    assert proactive.deadline_subject("Applications close on Monday", got[2]) == "Applications close"

    s = Store(":memory:")
    w = s.open_window(ts=seen)
    f = s.add_frame(w, "chrome.exe", "Careers", ts=seen)
    s.add_text(f, "uia", "Applications close on Monday\nPosted 2 days ago\nLast updated on 1 October 2026")
    asked = []
    n = proactive.find_deadlines(s.new_text(0, 0)[0], lambda line: asked.append(line) or True,
                                 frozenset(), s, [10])
    assert n == 1 and asked == ["Applications close on Monday"], asked
    assert proactive.find_deadlines(s.new_text(0, 0)[0], lambda l: True, frozenset(), s, [10]) == 0, "stored once"
    sun_eve = int(datetime(2026, 10, 4, 18, 0).timestamp() * 1000)
    cards = proactive.deadline_cards(s, sun_eve)
    assert [c[2] for c in cards] == ["Tomorrow: Applications close"], cards
    s.set_deadline_state(cards[0][0], cards[0][1])
    assert proactive.deadline_cards(s, sun_eve + MIN) == [], "one evening card"
    mon_am = int(datetime(2026, 10, 5, 8, 0).timestamp() * 1000)
    assert [c[2] for c in proactive.deadline_cards(s, mon_am)] == ["Today: Applications close"]
    print("ok  deadlines: dates found, model asked once, evening and morning cards")


def day_store() -> Store:
    s = Store(":memory:")
    w = s.open_window(ts=NOW - 3 * 3600_000)
    t0 = NOW - 3 * 3600_000
    for i in range(20):                                             # 20 min on the deck
        s.add_frame(w, "chrome.exe", "Pricing deck - Google Slides - Google Chrome", ts=t0 + i * MIN,
                    url="https://docs.google.com/presentation/d/x")
    s.add_frame(w, "Discord.exe", "#general", ts=t0 + 21 * MIN)
    return s


def test_resume_focus_offer_recap_and_mutes():
    s = day_store()
    before = NOW - 3 * 3600_000 + 21 * MIN
    line, payload = proactive.resume_card(s, before)
    assert line == "Left off: Pricing deck - Google" or line.startswith("Left off: Pricing deck"), line
    assert payload["url"] == "https://docs.google.com/presentation/d/x"
    assert proactive.focus_offer(s, before) == "Pricing deck - Google Slides", proactive.focus_offer(s, before)
    assert proactive.recap_card(s, NOW) is None, "before the recap hour"
    eve = int(FRI.replace(hour=22).timestamp() * 1000)
    s2 = Store(":memory:")
    w = s2.open_window(ts=eve)
    for i in range(40):
        s2.add_frame(w, "Code.exe", "main.py", ts=eve - 3600_000 + i * MIN)
    assert proactive.recap_card(s2, eve)[0] == "Today: 44m, mostly VS Code"
    s2.add_card("RECAP", "x", ts=eve)
    assert proactive.recap_card(s2, eve + MIN) is None, "once a day"

    for _ in range(config.MUTE_AFTER_DISMISSALS):
        cid = s.add_card("RECALL", "Same x as Tue", ts=NOW, app="Discord")
        s.set_card_state(cid, "dismissed")
    assert s.muted("RECALL", "Discord", NOW - MIN, config.MUTE_AFTER_DISMISSALS)
    assert not s.muted("RECALL", "Chrome", NOW - MIN, config.MUTE_AFTER_DISMISSALS), "only where you waved them off"
    s.set_card_state(s.add_card("RECALL", "y", ts=NOW, app="Discord"), "used")
    assert not s.muted("RECALL", "Discord", NOW - MIN, config.MUTE_AFTER_DISMISSALS), "one you used un-mutes it"
    print("ok  resume, focus offer, recap once a day, learned mutes")


def test_proactive_tick_shows_and_offers():
    s, m = day_store(), Memory(":memory:")
    shown, offers, said = [], [], []
    p = proactive.Proactive(s, m, lambda k, line, pay: shown.append((k, line)),
                            offer=lambda k, d: offers.append((k, d)), say=said.append)
    t = NOW - 3 * 3600_000 + 21 * MIN
    m.add_reminder("call Sam", t - 1)
    p.tick(t, "chrome.exe", "x")
    assert ("REMIND", "call Sam") in shown and said == ["Reminder: call Sam"]
    assert offers == [("focus", "Pricing deck - Google Slides")] and shown[-1][0] == "SUGGEST"
    p.tick(t + MIN * 2, "chrome.exe", "x")
    assert len(offers) == 1, "one offer, then quiet for hours"
    p.on_capture(t + 3600_000, t)
    assert shown[-1][0] == "RESUME"
    print("ok  proactive: reminder spoken, focus offered once, welcome back")


def test_asker_hands_free_and_offers():
    events, spoken, did = [], [], []
    ask_mod.now_ms = lambda: NOW
    acts = {"focus": lambda t: did.append(("focus", t)), "state": lambda: {},
            "remind": lambda *a: did.append(("remind", *a)), "reminders": lambda: [], "unremind": lambda: None,
            "curtain": lambda on: did.append(("curtain", on)), "open_file": lambda p: did.append(("file", p))}
    a = ask_mod.Asker(day_store(), events.append, speak=spoken.append, actions=acts)

    def turn(fn):
        events.clear()
        fn()
        assert a.wait_idle(10)
        return list(events)

    assert a.hear(0, "mic", "next") is False, "no wake word, nothing shown: not for Jimmy"
    a.nav_until = NOW + 10_000
    ev = turn(lambda: a.hear(0, "mic", "scroll down"))
    assert ev[0] == {"type": "ui", "action": "scroll", "dir": "down"} and spoken == [], "silent, instant"
    ev = turn(lambda: a.hear(0, "mic", "Jimmy, next"))
    assert ev[0]["action"] == "step", "one nav word after the wake word is a command, not 'listen'"

    a.make_offer("focus", "Pricing deck")
    assert a.hear(0, "mic", "yes") is False, "a card's offer needs the wake word"
    turn(lambda: a.hear(0, "mic", "Jimmy, yes"))
    assert did[-1] == ("focus", "Pricing deck") and a.offer is None

    a.make_offer("event", {"title": "Interview", "date": "2026-10-09", "start": "15:00", "end": "", "where": ""}, bare=True)
    with tempfile.TemporaryDirectory() as d:
        saved = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            turn(lambda: a.hear(0, "mic", "yes"))
        finally:
            config.DATA_DIR = saved
    assert did[-1][0] == "file" and did[-1][1].endswith("2026-10-09-interview.ics"), did[-1]

    turn(lambda: a.hear(0, "mic", "Jimmy, remind me in 10 minutes to stretch"))
    assert did[-1] == ("remind", "stretch", NOW + 10 * MIN, None)
    turn(lambda: a.hear(0, "mic", "Jimmy, curtain"))
    assert did[-1] == ("curtain", True)

    a.last_evidence = [{"ts": NOW, "url": "https://example.com/a"}, {"ts": NOW, "url": None}]
    ev = turn(lambda: a.hear(0, "mic", "Jimmy, open that page"))
    assert {"type": "open_url", "url": "https://example.com/a"} in ev
    a.shown = 1
    ev = turn(lambda: a.hear(0, "mic", "Jimmy, open that page"))
    assert ev[-1]["text"] == "I don't have a page link for that."

    ev = turn(lambda: a.ask("show me yesterday at 3pm"))
    got = next(e for e in ev if e["type"] == "open_view")
    assert got["view"] == "timeline" and datetime.fromtimestamp(got["ts"] / 1000).strftime("%a %H:%M") == "Thu 15:00"
    print("ok  asker: hands-free nav, offers by voice, reminders, curtain, open page, goto")


def test_calendar_file_and_event_checks():
    assert proactive.valid_event({"title": ""}) is None and proactive.valid_event({"title": "x", "date": "Fri"}) is None
    ev = proactive.valid_event({"title": "Interview, Acme; round 2", "date": "2026-10-09", "start": "15:00", "end": "99:00"})
    assert ev["end"] == "", "a bad time is dropped, not guessed"
    with tempfile.TemporaryDirectory() as d:
        text = proactive.calendar_file(ev, Path(d)).read_text(encoding="utf-8")
    assert "DTSTART:20261009T150000" in text and "DTEND:20261009T160000" in text
    assert "SUMMARY:Interview\\, Acme\\; round 2" in text
    print("ok  calendar: checked by code, escaped, an hour by default")


def test_urls_and_migration():
    from ambient.screen import clean_url
    assert clean_url("www.bank.com/acct?session=abc#top") == "https://www.bank.com/acct"
    assert clean_url("how to bake bread") is None and clean_url("chrome://settings") is None
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "old.db"
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE frames (id INTEGER PRIMARY KEY, ts INT NOT NULL, window_id TEXT, app TEXT, "
                  "title TEXT, thumb_path TEXT, face_count INT DEFAULT 0)")
        c.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, ts INT NOT NULL, type TEXT NOT NULL, "
                  "line TEXT NOT NULL, evidence TEXT, state TEXT DEFAULT 'shown')")
        c.commit()
        c.close()
        s = Store(db)
        s.add_frame("w", "chrome.exe", "x", ts=1, url="https://a.b/c")
        assert s.timeline(0, 2)[0]["url"] == "https://a.b/c", "an older database gains the column"
        s.close()
    print("ok  urls cleaned; older databases migrate")


def test_presence_states_never_recognise():
    from ambient.presence import Presence, Tracker, facing
    looking = [0, 0, 40, 40, 10, 15, 30, 15, 20, 25, 12, 32, 28, 32, 0.9]   # nose centred below the eyes
    turned = [0, 0, 40, 40, 10, 15, 30, 15, 31, 25, 12, 32, 28, 32, 0.9]    # nose out past an eye
    assert facing(looking) and not facing(turned)
    t = Tracker()
    assert t.update(0, 1, True, False)[0] == "present"
    assert t.update(3, 0, False, False)[0] == "present", "a few seconds without a face is not away"
    assert t.update(3 + config.AWAY_S, 0, False, False)[0] == "away"
    assert t.update(10, 1, False, False)[0] == "away", "someone walking past, not looking: still away"
    t.update(11, 1, True, False)
    assert t.update(11.01 + config.RETURN_S, 1, True, False)[0] == "present", "looking at the screen lifts it"
    t.update(20, 2, True, False)
    assert t.update(20 + config.WATCHED_S, 2, True, False)[0] == "watched"
    t.update(30, 0, False, True)
    assert t.update(41, 0, False, True)[0] == "off", "a covered lens turns presence off, not away"
    try:
        pickle.dumps(Presence(lambda i: None))
    except TypeError:
        pass
    else:
        raise AssertionError("Presence must refuse to be serialised")
    src = (Path(__file__).resolve().parents[1] / "ambient" / "presence.py").read_text(encoding="utf-8")
    assert "FaceRecognizerSF" not in src and "feature(" not in src, "the webcam path never computes a face vector"
    print("ok  presence: away / watched / off with hysteresis; no face vectors, no pickling")


def test_bus_curtain_rules():
    from ambient.bus import ContextBus
    b = ContextBus.__new__(ContextBus)
    b._api, b._curtain, b._manual_curtain, b._sensitive = None, False, False, False
    b._presence = {"state": "present"}
    assert not b.curtain_now()
    b._on_presence({"state": "away", "why": ""})
    assert b._curtain, "away -> curtain"
    b._on_presence({"state": "watched", "why": ""})
    assert not b._curtain, "someone looking at an ordinary page: panels hide, no curtain"
    b._sensitive = True
    b._refresh_curtain()
    assert b._curtain, "someone looking at a bank page: curtain"
    b.set_curtain(False)
    assert not b._curtain and b._presence["state"] == "present", "lifting by hand means you're here"
    b.set_curtain(True)
    b._on_presence({"state": "present", "why": ""})
    assert b._curtain, "a curtain you drew stays until you lift it"
    print("ok  bus: when the curtain falls and lifts")


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
