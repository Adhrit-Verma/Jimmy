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
# MoE with ~3B active parameters: chosen for "feels instant" (D15). Picked from
# the live model list, NOT yet measured -- there was no key when it was chosen.
MODEL = os.environ.get("JIMMY_MODEL") or "nvidia/nemotron-3.5-lightning-30b-a3b"
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
