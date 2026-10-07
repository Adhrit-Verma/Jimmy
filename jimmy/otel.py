"""Decision traces as OpenTelemetry GenAI spans, to a local file (D51, A10).

`jimmy trace` stays the primary log. This writes the same requests in the standard
shape, so local tools (Jaeger, Grafana Tempo, Phoenix, an OTel collector reading the
file) can show them: one `invoke_agent jimmy` span per request, with a `chat {model}`
span per model step and an `execute_tool {name}` span after it.

Following the GenAI convention's default, no content is recorded: not what was heard
or said, not prompts, not tool arguments (typed text is the user's words; control names
are screen content). Only names, timings, token counts and the route. No dependency:
the OTLP JSON is written by hand. Never sent anywhere.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

_LOCK = threading.Lock()


def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _span(trace_id: str, name: str, start_ms: int, end_ms: int, attrs: dict, parent: str = "",
          kind: int = 1, error: bool = False) -> dict:
    s = {"traceId": trace_id, "spanId": secrets.token_hex(8), "name": name, "kind": kind,
         "startTimeUnixNano": str(int(start_ms) * 1_000_000),
         "endTimeUnixNano": str(int(max(end_ms, start_ms)) * 1_000_000),
         "attributes": [_attr(k, v) for k, v in attrs.items() if v not in (None, "")]}
    if parent:
        s["parentSpanId"] = parent
    if error:
        s["status"] = {"code": 2}
    return s


def spans(t: dict) -> list[dict]:
    """One trace row (as Memory.add_trace gets it) -> spans, root first."""
    tid = secrets.token_hex(16)
    t0 = int(t.get("ts") or 0) + int(t.get("wait_ms") or 0)
    end = t0 + int(t.get("ms") or 0)
    said = str(t.get("said") or "")
    root = _span(tid, "invoke_agent jimmy", t0, end,
                 {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "jimmy",
                  "jimmy.route": t.get("route") or "", "jimmy.via": t.get("via") or "",
                  "jimmy.wait_ms": int(t.get("wait_ms") or 0), "jimmy.steps": len(t.get("steps") or [])},
                 error=said.startswith("error"))
    out, at = [root], t0
    for st in t.get("steps") or []:
        if not isinstance(st, dict):
            continue
        tool = str(st.get("tool") or "")
        ms, tool_ms = int(st.get("ms") or 0), int(st.get("tool_ms") or 0)
        if ms:
            out.append(_span(tid, f"chat {st.get('model') or 'default'}", at, at + ms,
                             {"gen_ai.operation.name": "chat", "gen_ai.request.model": st.get("model") or "",
                              "gen_ai.usage.input_tokens": int(st.get("prompt") or 0) or None,
                              "gen_ai.usage.output_tokens": int(st.get("out") or 0) or None,
                              "gen_ai.usage.cache_read.input_tokens": int(st.get("cached") or 0) or None,
                              "jimmy.slow": bool(st.get("slow")) or None},
                             parent=root["spanId"], kind=3))
            at += ms
        if tool:
            check = str(st.get("check") or "")
            out.append(_span(tid, f"execute_tool {tool}", at, at + tool_ms,
                             {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool,
                              "jimmy.speculative": bool(st.get("speculative")) or None,
                              "jimmy.check": "pass" if check.startswith("\u2713") else
                              "fail" if check.startswith("\u2717") else None},
                             parent=root["spanId"], error=check.startswith("\u2717")))
            at += tool_ms
    return out


def export(t: dict, path: str | os.PathLike) -> None:
    """Append one request as an OTLP JSON line. Never raises: tracing is optional."""
    try:
        line = {"resourceSpans": [{"resource": {"attributes": [_attr("service.name", "jimmy")]},
                                   "scopeSpans": [{"scope": {"name": "jimmy.agent"}, "spans": spans(t)}]}]}
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[otel] not written: {type(exc).__name__}: {exc}")
