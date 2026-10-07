"""Tunables for the Jimmy core. Same rule as ambient/config.py: knobs live here."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# D44: KEY=value lines from .env at the repo root (git-ignored) fill in whatever the
# process environment doesn't already set: the API keys, JIMMY_PROVIDER, JIMMY_MODEL.
try:
    for _line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        _k, _eq, _v = _line.strip().partition("=")
        if _eq and _k and not _k.startswith("#"):
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
except OSError:
    pass
DATA_DIR = Path(os.environ.get("JIMMY_DATA") or ROOT / "data")
MEMORY_DB = DATA_DIR / "jimmy.db"
# D51 (A10): each request's trace also goes to this file as OpenTelemetry GenAI spans
# (OTLP JSON, one line a request) for local tools: Jaeger, Phoenix, an OTel collector's
# otlpjsonfile receiver. No prompts, no heard or said text, no tool arguments (the
# convention's default). Local file only. JIMMY_OTEL=1 turns it on.
OTEL_FILE = DATA_DIR / "logs" / "otel.jsonl" if os.environ.get("JIMMY_OTEL") == "1" else None
AMBIENT_DB = DATA_DIR / "ambient.db"   # read-only from here; the ambient layer writes it

# --- the one LLM client (D14) -------------------------------------------------
# D44: which cloud. "nvidia" is free (NIM) and is the default; "openai" is paid
# (GPT-6 Luna: $0.10 in / $0.50 out per 1M, ~Rs 270-455 a month at our usage).
PROVIDER = os.environ.get("JIMMY_PROVIDER") or "nvidia"
OPENAI = PROVIDER == "openai"
API_KEY_ENV = "OPENAI_API_KEY" if OPENAI else "NVIDIA_API_KEY"
BASE_URL = os.environ.get("JIMMY_LLM_BASE_URL") or (
    "https://api.openai.com/v1" if OPENAI else "https://integrate.api.nvidia.com/v1")
# OpenAI's reasoning, when a call asks for thinking (cards). Tool calls on Chat
# Completions need "none" (gpt-6-luna's model page), so the agent never reasons.
REASONING_EFFORT = os.environ.get("JIMMY_REASONING") or "low"
# D43: nemotron-3-super (D17's pick) reached end of life on 2026-10-03 (HTTP 410).
# Measured that day, thinking off: nemotron-3-ultra answers through Jimmy's prompt in
# 1.0-1.4 s to first word, 2.0-2.5 s in full, clean; but it returned HTTP 500 on 30
# of 130 agent tool calls. gpt-oss-20b picked the right tool on 120/130, median
# 1.4 s, so it drives the agent. nemotron-3.5-lightning took 45-66 s and wrote
# garbage. The endpoint's public model list is NOT what an account can use: several
# listed models return 404 or time out. Measure before switching.
MODEL = os.environ.get("JIMMY_MODEL") or ("gpt-6-luna" if OPENAI else "nvidia/nemotron-3-ultra-550b-a55b")
TOOLS_MODEL = os.environ.get("JIMMY_TOOLS_MODEL") or (MODEL if OPENAI else "openai/gpt-oss-20b")
# A retired model (404/410) moves the chat to the next of these instead of failing.
MODEL_FALLBACKS = ("gpt-5.4-nano",) if OPENAI else ("openai/gpt-oss-20b",)
# Thinking off: ~1 s to first word. On: ~2.5 s, same answer quality on recall
# questions. Turn it on per call for heavy syntheses, not for chat.
THINKING = False
# D41: seeing the screen. Probed 2026-10-03 with drawn images (an invoice + chart, an
# editor with an error): of 81 listed models only these answered for this key.
# nemotron-3-nano-omni: 0.7-3.5 s, read the error and gave a concrete fix, but also
# returned 503 "request limit reached" once; llama-3.2-11b-vision: 1.1-9 s, vaguer.
# Gemma 4, Kimi K3, GLM-5.3 and llama-3.2-90b-vision timed out; others 404.
# Tried in order, once each; then the answer falls back to the window's text alone.
VISION_MODELS = tuple(filter(None, (os.environ.get("JIMMY_VISION_MODEL"),
                                    *((MODEL,) if OPENAI else (
                                        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                                        "meta/llama-3.2-11b-vision-instruct")))))
VISION_READ_TIMEOUT_S = 20.0
TEMPERATURE = 0.3
MAX_TOKENS = 600
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 60.0
RETRY_STATUSES = {429, 502, 503, 504}
RETRY_WAIT_S = 1.5

# --- retrieval ----------------------------------------------------------------
MAX_CONTEXT_CHARS = 6000     # hard cap on captured text sent to the cloud per question
HISTORY_TURNS = 6            # prior chat turns replayed for continuity
SEARCH_HITS = 12
SNIPPET_TOKENS = 48
MEMORY_HITS = 5
DEFAULT_LOOKBACK_H = 2       # "what was I doing" with no time words -> the last 2 hours
COVERAGE_GAP_MIN = 5         # capture gaps at least this long are named in the context as unknown

# --- card engine, Tier 2 (Stage 3, D19) ------------------------------------
CARD_MAX_WORDS = 7           # the spec: "never more than seven words"
CARD_THINKING = True         # cards aren't latency-bound; let the model reason (D17)
CARD_MAX_TOKENS = 2500       # thinking writes reasoning into the reply; 400 ran out before the JSON
FOCUS_INTENT_MAX_H = 8       # a stated focus older than this has expired

# --- local model via Ollama (D20) ------------------------------------------
# Same OpenAI-compatible client, second endpoint. Card decisions run here by
# default: private (screen text stays on the laptop), free, and immune to the
# free tier's 503 "overloaded". Chat answers still use the cloud model.
# 127.0.0.1, not "localhost" (D38): on Windows "localhost" tries IPv6 first and
# Ollama listens on IPv4, so every new connection waited ~2.4 s for the fallback.
# Measured: a new connection 2.8 s via localhost, 0.7 s via 127.0.0.1.
LOCAL_BASE_URL = os.environ.get("JIMMY_LOCAL_URL") or "http://127.0.0.1:11434/v1"
LOCAL_MODEL = os.environ.get("JIMMY_LOCAL_MODEL") or "qwen2.5:3b"
CARD_ENGINE = os.environ.get("JIMMY_CARD_ENGINE") or "local"   # "local" | "cloud"
# D51 (A8): a local Ollama model as the last fallback for an agent step, after the cloud's
# two (the cloud down or too slow). Empty = off. Must replace the cards model in VRAM, not
# sit beside it (e.g. qwen3:4b for both): measure eval_tools.py, the card set and VRAM first.
LOCAL_TOOLS_MODEL = os.environ.get("JIMMY_LOCAL_TOOLS") or ""
# RECALL needs two yeses (D22): the local model filters, the cloud confirms. Only
# the few local yeses leave the laptop. "none" = local only (lower precision).
RECALL_VERIFY = os.environ.get("JIMMY_RECALL_VERIFY") or "cloud"

# --- embeddings, Stage 5 (D24) ----------------------------------------------
# bge-m3 via local Ollama: multilingual (English + Hindi/Hinglish), chosen by the
# human over embeddinggemma and nomic-embed-text. Text never leaves the laptop.
EMBED_MODEL = os.environ.get("JIMMY_EMBED_MODEL") or "bge-m3"
# D38: Ollama unloads a model 5 min after its last use, and the first question
# after that waited ~6 s for bge-m3 (664 MB) to load. An hour, asked on each call.
EMBED_KEEP_ALIVE = "60m"
# D50 (P6): run bge-m3 on the CPU (Ollama's num_gpu 0), leaving the GPU to Whisper and the
# cards model. Slower per call; NOT measured: check search time and nvidia-smi before using.
# Changing it makes Ollama reload the model once.
EMBED_ON_CPU = os.environ.get("JIMMY_EMBED_ON_CPU", "") == "1"
# D38: httpx closes an idle connection after 5 s by default, so the "one warm
# connection" (D15) was cold for nearly every real question. Keep it two minutes.
KEEPALIVE_S = 120
