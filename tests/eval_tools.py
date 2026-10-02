"""Live check of the model's tool pick (D35-D37), against the real endpoint.
`python tests/eval_tools.py`. Needs NVIDIA_API_KEY and the network; not part of
the offline suites. Re-run when the model, the prompt (ask.TOOLS_Q) or the tool
list changes, and keep the numbers in DECISIONS-AND-WHY.md.

Each case: what the user said, and the tools that would be right. "answer"
cases also check that the English it returns routes where it should."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ambient.ask import TOOLS_Q, _json_obj, route  # noqa: E402
from jimmy.llm import LLM  # noqa: E402

CASES = [
    # English, phrasings the rules don't know
    ("put the privacy thing over my stuff", {"curtain"}),
    ("bring the curtain down", {"curtain"}),
    ("copy only bold letters", {"cannot"}),
    ("make your voice a bit quieter", {"volume"}),
    ("turn the volume way down", {"volume"}),
    ("close the chrome window", {"cannot"}),
    ("click the login button", {"cannot"}),
    ("type my password in", {"cannot"}),
    ("get rid of all your windows", {"close_ui"}),
    ("take me to the timeline", {"open"}),
    ("stop recording me for a bit", {"pause"}),
    ("start watching again", {"resume"}),
    ("save my face so you know it's me", {"remember_face"}),
    ("scroll a bit further down", {"scroll"}),
    ("set a reminder for 5 to call Sam", {"remind"}),
    ("open the page I was just looking at", {"open_page"}),
    ("go to the next one", {"step"}),
    ("close that picture", {"close", "close_ui"}),
    ("move to yesterday afternoon", {"goto"}),
    ("turn this off", {"ask_back", "curtain", "volume", "pause"}),
    # Hindi
    ("मेरी स्क्रीन पर क्या है", {"answer:screen"}),
    ("कल मैंने डिस्कॉर्ड कितनी देर चलाया", {"answer:stats"}),
    ("पर्दा लगा दो", {"curtain"}),
    ("पर्दा हटा दो", {"curtain"}),
    ("थोड़ा धीरे बोलो", {"volume"}),
    ("पाँच मिनट के लिए रुक जाओ", {"pause"}),
    ("मेरा चेहरा याद रखो", {"remember_face"}),
    ("मेरा चेहरा भूल जाओ", {"forget_face"}),
    ("नीचे स्क्रॉल करो", {"scroll"}),
    ("टाइमलाइन खोलो", {"open"}),
    ("दस मिनट बाद पानी पीने की याद दिलाना", {"remind"}),
    ("सब बंद कर दो", {"close_ui", "close"}),
    ("अगला दिखाओ", {"step"}),
    ("कल शाम को मैं क्या देख रहा था", {"answer:recall", "answer:goto", "goto"}),
    # D39: timers and forgetting a span
    ("wipe whatever you recorded last week", {"forget"}),
    ("could you count down three minutes for me", {"timer"}),
    ("पाँच मिनट का टाइमर लगाओ", {"timer"}),
    ("टाइमर बंद करो", {"cancel_timer"}),
    ("सितंबर का सारा डेटा डिलीट कर दो", {"forget"}),
    # D40
    ("set up the eye tracking thing again", {"calibrate_eyes"}),
    ("मेरी आँखों का कैलिब्रेशन करो", {"calibrate_eyes"}),
]


def main() -> int:
    llm = LLM()
    if not llm.configured:
        print("no NVIDIA_API_KEY: nothing to measure")
        return 2
    right, times = 0, []
    for text, ok in CASES:
        t0 = time.time()
        try:
            got = _json_obj(llm.chat([{"role": "system", "content": TOOLS_Q}, {"role": "user", "content": text}],
                                     max_tokens=160, temperature=0.0)) or {}
        except Exception as exc:
            got = {"tool": f"error {type(exc).__name__}"}
        times.append(time.time() - t0)
        tool = got.get("tool")
        english = (got.get("args") or {}).get("english") or got.get("english") or ""
        label = f"answer:{route(english)[0]}" if tool == "answer" and english else tool
        hit = label in ok or tool in ok
        right += hit
        print(f"{'ok ' if hit else 'MISS'} {times[-1]:4.1f}s  {text!r} -> {label}  {got.get('args', {})}")
    times.sort()
    print(f"\n{right}/{len(CASES)} right; median {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s")
    return 0 if right >= 0.9 * len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
