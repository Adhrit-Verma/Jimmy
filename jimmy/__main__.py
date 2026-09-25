"""CLI: python -m jimmy {chat,ask,remember,focus,doctor}"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Iterable

from . import config

HELP = """commands:  /remember <fact>   keep something for later
           /context           show exactly what was sent to the model last time
           /quit              leave (or ctrl-c)"""


def _print_stream(pieces: Iterable[str]) -> None:
    for piece in pieces:
        print(piece, end="", flush=True)
    print()


def _chat(session: str) -> int:
    from .core import Jimmy
    from .llm import LLMError
    jim = Jimmy.default()
    mode = f"model {jim.llm.model}" if jim.llm.configured else \
        f"OFFLINE, {config.API_KEY_ENV} not set: answers show retrieval only"
    print(f"Jimmy ({mode}). /help for commands.")
    try:
        while True:
            try:
                line = input("\nyou> ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line in ("/quit", "/exit"):
                break
            if line == "/help":
                print(HELP)
                continue
            if line == "/context":
                print(jim.last_context or "(nothing was sent yet)")
                continue
            if line.startswith("/remember"):
                fact = line[len("/remember"):].strip()
                print("kept." if jim.remember(fact) else "usage: /remember <fact>")
                continue
            print("jimmy> ", end="", flush=True)
            started = time.perf_counter()
            try:
                _print_stream(jim.ask_stream(line, session=session))
            except LLMError as exc:
                print(f"\n[error] {exc}")
                continue
            print(f"       ({time.perf_counter() - started:.1f}s)")
    except KeyboardInterrupt:
        print()
    finally:
        jim.close()
    return 0


def _doctor() -> int:
    from .llm import LLM, api_key
    import httpx
    bad = 0

    def row(ok: bool, name: str, detail: str) -> None:
        nonlocal bad
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:14s} {detail}")

    key = api_key()
    row(bool(key), "api key", f"{config.API_KEY_ENV} {'is set' if key else 'is NOT set'}")
    try:
        r = httpx.get(f"{config.BASE_URL}/models", timeout=10)
        ids = {m["id"] for m in r.json().get("data", [])}
        # Listed is not the same as usable by this account: the round trip decides.
        row(config.MODEL in ids, "model", f"{config.MODEL} "
            f"{'is listed' if config.MODEL in ids else 'is NOT in the endpoint model list'}")
    except Exception as exc:
        row(False, "endpoint", f"{config.BASE_URL} unreachable: {type(exc).__name__}")
    if key:
        llm = LLM(key)
        try:
            t = time.perf_counter()
            first, parts = None, []
            for piece in llm.chat_stream(
                    [{"role": "user", "content": "Reply with exactly one word: ready"}],
                    max_tokens=20):
                if first is None and piece.strip():
                    first = time.perf_counter() - t
                parts.append(piece)
            total, out = time.perf_counter() - t, "".join(parts).strip()
            # A model that rambles or thinks out loud must fail here, not pass as "ok".
            ok = out.lower().strip(" .!\"'") == "ready"
            timing = f"first word {first:.2f}s, total {total:.2f}s" if first else f"total {total:.2f}s"
            row(ok, "round trip", f"{timing} -> {out[:60]!r}"
                + ("" if ok else "  (expected just 'ready')"))
            row(first is not None and first < 3, "latency",
                "feels instant" if first and first < 1.5 else
                "usable" if first and first < 3 else "too slow for chat: consider JIMMY_MODEL")
        except Exception as exc:
            row(False, "round trip", str(exc)[:160])
        finally:
            llm.close()
    # The local model decides cards (D20): Ollama must be up and the model pulled.
    from .llm import local_llm
    loc = local_llm()
    try:
        t = time.perf_counter()
        out = loc.chat([{"role": "user", "content": "Reply with exactly one word: ready"}], max_tokens=10)
        ok = out.lower().strip(" .!\"'") == "ready"
        row(ok, "local model", f"{config.LOCAL_MODEL} via Ollama: {time.perf_counter() - t:.1f}s -> {out[:30]!r}"
            f" (card engine: {config.CARD_ENGINE})")
    except Exception as exc:
        row(config.CARD_ENGINE != "local", "local model",
            f"{config.LOCAL_MODEL} unreachable ({str(exc)[:80]}). Start Ollama and "
            f"`ollama pull {config.LOCAL_MODEL}`" + ("" if config.CARD_ENGINE == "local" else " (unused)"))
    finally:
        loc.close()
    row(config.AMBIENT_DB.exists(), "captures",
        f"{config.AMBIENT_DB}" + ("" if config.AMBIENT_DB.exists() else " missing: run `python -m ambient run`"))
    row(True, "memory", str(config.MEMORY_DB))
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # model text on a cp1252 console
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="jimmy", description="Jimmy core")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat", help="talk to Jimmy in the terminal")
    c.add_argument("--session", default="default")
    a = sub.add_parser("ask", help="one question, one answer")
    a.add_argument("question")
    a.add_argument("--session", default="default")
    r = sub.add_parser("remember", help="keep a fact in Jimmy's memory")
    r.add_argument("fact")
    sub.add_parser("doctor", help="check the key, model, endpoint and data")
    f = sub.add_parser("focus", help="say what you mean to be doing (FOCUS cards), or show it")
    f.add_argument("intent", nargs="?")
    f.add_argument("--clear", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "chat":
        return _chat(args.session)
    if args.cmd == "doctor":
        return _doctor()

    from .core import Jimmy
    from .llm import LLMError
    jim = Jimmy.default()
    try:
        if args.cmd == "focus":
            if args.clear or args.intent:
                jim.memory.set_intent(None if args.clear else args.intent)
            cur = jim.memory.current_intent(config.FOCUS_INTENT_MAX_H)
            print(f"focus: {cur['text']}" if cur else "no current focus")
            return 0
        if args.cmd == "remember":
            print("kept." if jim.remember(args.fact) else "nothing to keep.")
            return 0
        _print_stream(jim.ask_stream(args.question, session=args.session))
        return 0
    except LLMError as exc:
        print(f"[error] {exc}")
        return 1
    finally:
        jim.close()


if __name__ == "__main__":
    sys.exit(main())
