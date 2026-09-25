"""One runnable check for stage 3 (trigger gate). `python tests/test_stage3.py`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ambient import config  # noqa: E402
from ambient.db import Store  # noqa: E402
from ambient.gate import Gate, is_question, replay, stems  # noqa: E402
from jimmy.cards import Card, CardEngine, parse  # noqa: E402
from jimmy.llm import LLM  # noqa: E402
from jimmy.memory import Memory  # noqa: E402

MIN = 60_000
T0 = 1_800_000_000_000  # a fixed "now" so nothing depends on the clock


class FakeEngine:
    """Tier 2 stand-in: records candidates, speaks (or not) on request."""
    def __init__(self, speak=True):
        self.speak, self.seen = speak, []

    def decide(self, cand):
        self.seen.append(cand)
        if not self.speak:
            return None, "silence"
        return Card(cand.type, cand.ts, "Same ingress bug as Monday", "test", cand.evidence, cand.key), "ok"


def history_store(filler: int = 80) -> Store:
    """90 min of filler, plus one earlier moment about a distinctive topic."""
    s = Store(":memory:")
    w = s.open_window(ts=T0 - 400 * MIN)
    for i in range(filler):   # enough blocks that the topic words are rare (< 3 %)
        f = s.add_frame(w, "chrome.exe", f"page {i}", ts=T0 - 390 * MIN + i * 10_000)
        s.add_text(f, "uia", f"weather lunch playlist garden {i} holiday football recipe")
    old = s.open_window(ts=T0 - 200 * MIN)   # > 2 h: a different sitting
    f = s.add_frame(old, "ms-teams.exe", "Chat | Priya", ts=T0 - 195 * MIN)
    s.add_text(f, "uia", "the kubernetes ingress certificate expired again on staging")
    return s


def feed_moment(g: Gate, start: int, app="Code.exe", title="ingress.yaml - infra", window="w-now",
                text="renewing the kubernetes ingress certificate for staging " * 5):
    for i in range(5):   # 4 minutes in one window, plenty of text
        g.observe_frame(start + i * MIN, app, title, window, text if i == 0 else "")
    g.observe_frame(start + 5 * MIN, "explorer.exe", "Downloads", "w-other", "")  # moment ends


def test_tier2_parsing_and_code_written_lines():
    from jimmy.cards import Candidate, focus_line, recall_line
    assert parse('Thinking... {"x": 1} then {"same": true, "thing": "ingress"}', "same") == \
        {"same": True, "thing": "ingress"}, "the last object with the key wins"
    assert parse("cut off mid-reasoning", "same") is None

    ev = {"ts": T0 - 3 * 24 * 60 * MIN, "where": "ms-teams.exe", "text": "the Kubernetes ingress certificate"}
    line = recall_line("ingress certificate", ev, T0)
    assert line and line.startswith("Same ingress certificate as ") and len(line.split()) <= 7
    assert line.split(" as ")[1][:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), \
        "an earlier day is named from the evidence's own timestamp"
    assert recall_line("error on Teams", ev, T0) is None, "words not in the evidence are refused"
    assert recall_line("the kubernetes ingress certificate", ev, T0) is None, "more than 3 words"
    today = recall_line("ingress", dict(ev, ts=T0 - 40 * MIN), T0)
    assert today and ":" in today.split(" as ")[1] and len(today.split(" as ")[1]) == 5, "same day: HH:MM"

    c = Candidate("FOCUS", T0, "r", "now", [{"ts": None, "where": "stated intent",
                                               "text": "finish the trigger gate replay today please"}])
    assert focus_line(c) == "Back to: finish the trigger gate replay", "intent's own words, <= 7"
    print("ok  tier 2 parsing and code-written lines")

def test_recall_fires_after_a_moment_and_only_on_the_past():
    s, eng = history_store(), FakeEngine(speak=False)
    g = Gate(s, eng)
    feed_moment(g, T0)
    assert len(eng.seen) == 1 and eng.seen[0].type == "RECALL", g.stats
    cand = eng.seen[0]
    assert cand.ts == T0 + 5 * MIN, "RECALL fires when the moment ENDS, not during it"
    assert any("kubernetes" in e["text"] for e in cand.evidence)
    assert "kubernetes" in cand.reason or "ingress" in cand.reason, cand.reason

    # The same moment again: its earlier match was already considered once.
    feed_moment(g, T0 + 20 * MIN, window="w-again")
    assert len(eng.seen) == 1, "no repeats of the same earlier item"

    # No look-ahead: the only match lies AFTER the moment, so nothing fires.
    s2, eng2 = history_store(), FakeEngine()
    s2.conn.execute("DELETE FROM text_blocks WHERE text LIKE '%kubernetes%'")
    s2.conn.commit()
    later = s2.add_frame(s2.open_window(ts=T0 + 60 * MIN), "ms-teams.exe", "later", ts=T0 + 60 * MIN)
    s2.add_text(later, "uia", "kubernetes ingress certificate")
    feed_moment(Gate(s2, eng2), T0)
    assert eng2.seen == [], "a replayed card must be one that could have fired live"
    print("ok  recall after a moment, past only")


def test_screen_furniture_is_not_content():
    """D22: a line seen in 3+ windows (sidebar, friend list, own name) never makes a RECALL."""
    s, eng = Store(":memory:"), FakeEngine()
    side = "Sunandha UI/UX resume review"            # a chat title in an always-visible sidebar
    for i in range(80):
        w = s.open_window(ts=T0 - 190 * MIN + i)
        f = s.add_frame(w, "chrome.exe", f"p{i}", ts=T0 - 190 * MIN + i * 10_000)
        s.add_text(f, "uia", f"weather lunch playlist {i}")
    for i in range(3):                               # the sidebar, in three earlier windows
        w = s.open_window(ts=T0 - 120 * MIN + i)
        f = s.add_frame(w, "claude.exe", "Claude", ts=T0 - 120 * MIN + i * MIN)
        s.add_text(f, "uia", f"{side}\nunrelated chat body number {i} about lunch")
    g = Gate(s, eng, history_until=T0)
    assert len(g.line_windows[side]) == 3 and g.content(f"{side}\nreal new content") == "real new content"
    feed_moment(g, T0, app="claude.exe", title="Claude", window="w-now",
                text=(side + "\n") * 2 + "short")
    assert eng.seen == [], "a moment made of sidebar lines must not produce a RECALL"
    assert g.stats["moment_too_small"] >= 1
    print("ok  screen furniture is not content")


def test_small_moments_and_generic_words_do_not_fire():
    s, eng = history_store(), FakeEngine()
    g = Gate(s, eng)
    g.observe_frame(T0, "Code.exe", "x", "w1", "kubernetes ingress certificate staging " * 20)
    g.observe_frame(T0 + 20_000, "explorer.exe", "y", "w2", "")     # 20 s: too short
    assert eng.seen == [] and g.stats["moment_too_small"] == 1
    assert len(stems(["responded", "response"])) == 1, "one idea, counted once"
    print("ok  small moments and generic words")


def test_hard_limits():
    s, eng = history_store(filler=250), FakeEngine(speak=True)   # keep the words rare
    for i in range(3):   # three more distinct earlier topics
        w = s.open_window(ts=T0 - 190 * MIN)
        f = s.add_frame(w, "ms-teams.exe", f"old {i}", ts=T0 - 190 * MIN + i)
        s.add_text(f, "uia", "the kubernetes ingress certificate expired " + ["alpha", "beta", "gamma"][i])
    g = Gate(s, eng)
    feed_moment(g, T0)
    assert g.stats["card RECALL"] == 1
    feed_moment(g, T0 + 7 * MIN, window="w2")        # 7 min later: inside the gap
    assert "blocked: too soon after the last card" in g.stats
    g.dismissed(T0 + 30 * MIN)
    feed_moment(g, T0 + 31 * MIN, window="w3",
                text="rotating the kubernetes ingress certificate on staging today " * 5)
    assert "blocked: cooldown after dismissal" in g.stats
    print("ok  hard limits: gap, cooldown")


def test_focus_needs_intent_nudges_once_and_does_not_nag():
    s, eng = Store(":memory:"), FakeEngine(speak=True)
    g = Gate(s, eng, intent="finish the trigger gate replay")
    t = T0
    for i in range(12):                              # 11 min on unrelated windows
        g.observe_frame(t + i * MIN, "Discord.exe", f"memes {i % 2}", "d", "")
    focus = [c for c in eng.seen if c.type == "FOCUS"]
    assert len(focus) == 1 and focus[0].evidence[0]["text"] == "finish the trigger gate replay"
    g.observe_frame(t + 13 * MIN, "Code.exe", "gate.py - Jimmy", "c", "")   # back on intent
    for i in range(14, 30):                          # drifts again within 45 min
        g.observe_frame(t + i * MIN, "Discord.exe", "memes", "d", "")
    assert len([c for c in eng.seen if c.type == "FOCUS"]) == 1, "one nudge, not nagging"
    assert g.stats["focus_repeat_held"] >= 1

    quiet = FakeEngine()
    g2 = Gate(s, quiet)                              # no intent stated: FOCUS never fires
    for i in range(30):
        g2.observe_frame(t + i * MIN, "Discord.exe", "memes", "d", "")
    assert quiet.seen == []
    print("ok  focus: needs intent, nudges once")


def test_question_heard_aloud():
    assert is_question("did we fix the ingress certificate on staging?")
    assert not is_question("we fixed it?") and not is_question("the certificate expired")
    s, eng = history_store(), FakeEngine(speak=False)
    g = Gate(s, eng)
    g.observe_speech(T0, T0 + 4000, "mic", "did we fix the kubernetes ingress certificate already?")
    assert g.stats["question_heard"] == 1 and eng.seen and eng.seen[0].type == "RECALL"
    print("ok  question heard aloud")


def test_intent_memory():
    m = Memory(":memory:")
    assert m.current_intent(8) is None
    m.set_intent("ship stage 3")
    assert m.current_intent(8)["text"] == "ship stage 3"
    m.set_intent(None)
    assert m.current_intent(8) is None, "clearing means no intent, not an empty one"
    m.set_intent("old goal")
    far = m.current_intent(8)["ts"] + 9 * 3600_000
    assert m.current_intent(8, now_ms=far) is None, "an intent expires"
    print("ok  intent memory")


def test_engine_end_to_end_with_mocked_llm():
    sent = []

    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content":
            'Thinking it over... {"same": true, "thing": "ingress certificate", "why": "same cert"}'}}]})

    llm = LLM(key="k", model="m", base_url="https://llm.test/v1", transport=httpx.MockTransport(handler))
    s = history_store()
    cards = []
    g = Gate(s, CardEngine(llm, thinking=True), on_card=cards.append)   # the cloud path
    feed_moment(g, T0)
    assert len(cards) == 1 and cards[0].line.startswith("Same ingress certificate as "), cards
    assert sent[0]["chat_template_kwargs"]["enable_thinking"] is True
    assert "<earlier>" in sent[0]["messages"][1]["content"]

    def invents(req):   # a model naming something that isn't in the evidence
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"same": true, "thing": "Teams chat error", "why": "x"}'}}]})
    bad = CardEngine(LLM(key="k", model="m", base_url="https://llm.test/v1",
                         transport=httpx.MockTransport(invents)))
    g2 = Gate(history_store(), bad, on_card=cards.append)
    feed_moment(g2, T0)
    assert len(cards) == 1, "an invented thing never becomes a card"

    from jimmy.cards import Candidate
    assert CardEngine(LLM(key="")).decide(Candidate("RECALL", T0, "r", "now"))[0] is None, "offline: silence"
    print("ok  engine end to end (mocked)")

def test_recall_needs_a_second_opinion_and_a_real_thing():
    """D22: the local model's yes needs the verifier's yes; dates aren't things."""
    from jimmy.cards import recall_line

    def model(same):
        def h(req):
            return httpx.Response(200, json={"choices": [{"message": {"content":
                json.dumps({"same": same, "thing": "ingress certificate", "why": "x"})}}]})
        return LLM(key="k", model="m", base_url="https://llm.test/v1", transport=httpx.MockTransport(h))

    for verifier_says, expect in ((True, 1), (False, 0)):
        cards = []
        g = Gate(history_store(), CardEngine(model(True), verifier=CardEngine(model(verifier_says))),
                 on_card=cards.append)
        feed_moment(g, T0)
        assert len(cards) == expect, f"verifier said {verifier_says}: {cards}"

    ev = {"ts": T0 - 3 * 24 * 60 * MIN, "where": "chrome.exe — GitHub", "text": "Joined Jun 13, 2026"}
    assert recall_line("Jun 13, 2026", ev, T0) is None, "a date is not a thing"
    print("ok  recall: second opinion, real things only")


def test_replay_reports_worst_hour():
    s, eng = history_store(), FakeEngine(speak=True)
    w = s.open_window(ts=T0)
    for i in range(5):
        f = s.add_frame(w, "Code.exe", "ingress.yaml - infra", ts=T0 + i * MIN)
        s.add_text(f, "uia", "renewing the kubernetes ingress certificate for staging " * 5 if i == 0 else "")
    s.add_frame(s.open_window(ts=T0 + 5 * MIN), "explorer.exe", "Downloads", ts=T0 + 5 * MIN)
    r = replay(s, T0 - MIN, T0 + 10 * MIN, eng)
    assert len(r["cards"]) == 1 and r["worst_hour"] == 1 and r["hours"] > 0
    assert config.MAX_CARDS_PER_HOUR <= 10, "the hard cap alone keeps any hour under the GO limit"
    print("ok  replay")


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
