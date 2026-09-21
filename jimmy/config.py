"""Tunables for the Jimmy core. Same rule as ambient/config.py: knobs live here."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("JIMMY_DATA") or ROOT / "data")
MEMORY_DB = DATA_DIR / "jimmy.db"
AMBIENT_DB = DATA_DIR / "ambient.db"   # read-only from here; the ambient layer writes it

# --- the one LLM client (D14) -------------------------------------------------
API_KEY_ENV = "NVIDIA_API_KEY"
BASE_URL = os.environ.get("JIMMY_LLM_BASE_URL") or "https://integrate.api.nvidia.com/v1"
# Measured 2026-09-22 (D17): ~1.0 s to first word, ~1.4 s for a full answer, clean
# output. The first pick, nemotron-3.5-lightning, took 159 s and leaked reasoning
# as plain text. The endpoint's public model list is NOT what an account can use:
# several listed models return 404 or time out. Measure before switching.
MODEL = os.environ.get("JIMMY_MODEL") or "nvidia/nemotron-3-super-120b-a12b"
# Thinking off: ~1 s to first word. On: ~2.5 s, same answer quality on recall
# questions. Turn it on per call for heavy syntheses, not for chat.
THINKING = False
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
