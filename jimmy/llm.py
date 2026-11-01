"""The one LLM client in this repo (D14). Nothing else may talk to a model API.

OpenAI-compatible chat completions against NVIDIA's endpoint. One httpx client
is kept open and reused, so every call after the first skips the TCP + TLS
handshake (D15). Responses can stream token by token.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Iterator

import httpx

from . import config


class LLMError(RuntimeError):
    def __init__(self, msg: str = "", status: int | None = None):
        super().__init__(msg)
        self.status = status               # D54: the HTTP status, when there was one


# D54: Gemini 3 checks that a tool call it made comes back with its thought signature; a
# call it didn't make (answered by the backup) carries Google's documented stand-in.
DUMMY_SIGNATURE = "skip_thought_signature_validator"


# Measured 2026-09-25: empties come in runs; twice-empty broke 3 of ~10 demo answers.
ATTEMPTS = 3
EMPTY = "the model returned an empty answer three times; try again"


def api_key(env: str | None = None) -> str | None:
    """The key from the environment, or from the user's registry environment.

    `setx` writes HKCU\\Environment but only new processes see it; reading the
    registry too means a key set a minute ago works without restarting the app.
    `env` (D54): another provider's variable. Gemini's key may also be GOOGLE_API_KEY.
    """
    names = [env or config.API_KEY_ENV]
    if names[0] == "GEMINI_API_KEY":
        names.append("GOOGLE_API_KEY")
    for name in names:
        key = os.environ.get(name)
        if key:
            return key.strip()
    from . import install                  # D60: keys typed in onboarding, DPAPI-encrypted
    stored = install.secrets() if install.SECRETS.exists() else {}
    for name in names:
        if stored.get(name):
            return stored[name]
    for name in names:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = (winreg.QueryValueEx(k, name)[0] or "").strip()
            if key:
                return key
        except OSError:
            continue
    return None


def endpoint_for(model: str) -> str:
    """D54: the provider a model id belongs to: "gemini-…" Google, "gpt-…" OpenAI, "org/…" NVIDIA."""
    m = model.lower()
    return "gemini" if m.startswith("gemini") else "openai" if m.startswith("gpt-") else "nvidia"


def for_model(model: str, like: "LLM | None" = None, **kw) -> "LLM":
    """D54: a client for one model, on its own provider's endpoint and key. `like`: a client
    whose key and transport to reuse when it's on the same provider (and in tests)."""
    url, env = config.ENDPOINTS[endpoint_for(model)]
    if like is not None and (like.base_url == url.rstrip("/") or like._transport is not None):
        return LLM(key=like.key, model=model, base_url=like.base_url, transport=like._transport, **kw)
    return LLM(key=api_key(env), model=model, base_url=url, **kw)


def _pacific_midnight_in(now: float | None = None) -> float:
    """Seconds until the next midnight Pacific, when Google's daily quotas reset. This
    Python has no tz database (no tzdata on Windows), so Pacific is taken as UTC-8: exact
    in winter, an hour late in summer, never early."""
    now = time.time() if now is None else now
    return 86_400 - ((now - 8 * 3600) % 86_400)


class ThinkFilter:
    """Strip <think>...</think> from streamed text, even when a tag is split
    across chunks. Some NVIDIA-hosted models reason out loud; the user sees only
    the answer."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = []
        while True:
            tag = self.CLOSE if self.inside else self.OPEN
            i = self.buf.find(tag)
            if i >= 0:
                if not self.inside:
                    out.append(self.buf[:i])
                self.buf = self.buf[i + len(tag):]
                self.inside = not self.inside
                continue
            # Hold back a tail that could be the start of a tag.
            keep = next((n for n in range(min(len(tag) - 1, len(self.buf)), 0, -1)
                         if tag.startswith(self.buf[-n:])), 0)
            if not self.inside:
                out.append(self.buf[:len(self.buf) - keep])
            self.buf = self.buf[len(self.buf) - keep:]
            return "".join(out)

    def flush(self) -> str:
        rest, self.buf = ("" if self.inside else self.buf), ""
        return rest


class LLM:
    def __init__(self, key: str | None = None, model: str = config.MODEL,
                 base_url: str = config.BASE_URL, transport: httpx.BaseTransport | None = None,
                 attempts: int | None = None, read_timeout_s: float | None = None):
        self.key = key if key is not None else api_key()
        self.model = model
        # D43: only the default cloud client has a tools model and fallbacks; vision
        # and local clients keep exactly the model they were given.
        default = model == config.MODEL and base_url == config.BASE_URL
        self.tools_model = config.TOOLS_MODEL if default else None
        self.fallbacks = [m for m in config.MODEL_FALLBACKS if m != model] if default else []
        self.attempts = attempts or ATTEMPTS   # D41: a vision model with a fallback tries once
        self.read_timeout_s = read_timeout_s or config.READ_TIMEOUT_S
        self.base_url = base_url.rstrip("/")
        self.openai = "api.openai.com" in self.base_url
        self.gemini = "generativelanguage.googleapis.com" in self.base_url
        self._transport = transport
        self._client: httpx.Client | None = None
        # D54: the default client on a free tier gets the other provider as its backup.
        self.backup: LLM | None = None
        self._down_until = 0.0
        self._model_down: dict[str, float] = {}   # D54: a model that just failed rests (BACKUP_RETRY_S)
        if default and config.BACKUP_PROVIDER and transport is None:   # a test's client never reaches out
            url, env = config.ENDPOINTS[config.BACKUP_PROVIDER]
            # D58: the backup has limits too. On 2026-11-01 gpt-oss hung while Gemini was down
            # and, with 3 tries of 60 s, one eval step took 186 s.
            b = LLM(key=api_key(env), model=config.NVIDIA_MODEL, base_url=url, attempts=2,
                    read_timeout_s=config.GEMINI_ANSWER_S)
            b.tools_model, b.fallbacks = config.NVIDIA_TOOLS_MODEL, [config.NVIDIA_TOOLS_MODEL]
            self.backup = b if b.key else None

    @property
    def configured(self) -> bool:
        return bool(self.key) or bool(self.backup and self.backup.key)

    def _route(self) -> "LLM | None":
        """D54: the backup, while this provider is down or has no key; else None (this one)."""
        if self.backup is None:
            return None
        return self.backup if not self.key or time.time() < self._down_until else None

    def _trip(self, exc: LLMError) -> bool:
        """D54: this provider failed a call: the backup takes over until it could answer
        again (a daily quota: the next midnight Pacific). False without a backup."""
        if self.backup is None:
            return False
        text = str(exc)
        daily = exc.status == 429 and any(w in text.lower() for w in ("perday", "per day", "daily"))
        wait = (_pacific_midnight_in() if daily else 3600 if exc.status in (401, 403)
                else config.BACKUP_RETRY_S)
        self._down_until = time.time() + wait
        print(f"[jimmy] {self.model}: {text[:120]!r}; {self.backup.model} answers for the next "
              f"{wait / 60:.0f} min", file=sys.stderr, flush=True)
        return True

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url, transport=self._transport,
                headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"},
                timeout=httpx.Timeout(self.read_timeout_s, connect=config.CONNECT_TIMEOUT_S),
                limits=httpx.Limits(keepalive_expiry=config.KEEPALIVE_S))
        return self._client

    def warm(self) -> None:
        """Open (or keep) the connection before it's needed: a cheap GET of the model
        list, so the TLS handshake overlaps with gathering evidence (D38). Errors are
        ignored: the real call reports them."""
        if not self.configured:
            return
        try:
            self._http().get("/models", timeout=httpx.Timeout(10, connect=5))
        except Exception:
            pass

    def _body(self, messages, stream, max_tokens, temperature, thinking=None) -> dict:
        # Both spellings of the switch: NVIDIA's chat templates differ by model family.
        think = config.THINKING if thinking is None else thinking
        messages = self._wire(messages)
        if self.gemini:
            # D54: Gemini 3 thinks at least "low", wants its own temperature, and may count
            # thinking against max_tokens: room is left so an answer isn't cut to nothing.
            return {"model": self.model, "messages": messages, "stream": stream,
                    "max_tokens": max_tokens + config.GEMINI_THINK_ROOM,
                    "reasoning_effort": "medium" if think else config.GEMINI_REASONING}
        if self.openai:
            # D44: OpenAI's reasoning models take an effort, count reasoning inside
            # max_completion_tokens (so thinking gets headroom), and set temperature themselves.
            return {"model": self.model, "messages": messages, "stream": stream,
                    "max_completion_tokens": max_tokens + (2000 if think else 0),
                    "reasoning_effort": config.REASONING_EFFORT if think else "none"}
        return {"model": self.model, "messages": messages, "stream": stream,
                "max_tokens": max_tokens, "temperature": temperature,
                "chat_template_kwargs": {"enable_thinking": think, "thinking": think}}

    def _wire(self, messages: list[dict]) -> list[dict]:
        """D54: tool calls as this endpoint wants them. Gemini: each keeps its thought
        signature, and one Gemini didn't make gets the stand-in. Others: Google's
        `extra_content` is dropped (a strict endpoint may refuse an unknown field)."""
        if not any(m.get("tool_calls") for m in messages):
            return messages
        out = []
        for m in messages:
            if not m.get("tool_calls"):
                out.append(m)
                continue
            calls = []
            for c in m["tool_calls"]:
                c = dict(c)
                if self.gemini:
                    if not ((c.get("extra_content") or {}).get("google") or {}).get("thought_signature"):
                        c["extra_content"] = {"google": {"thought_signature": DUMMY_SIGNATURE}}
                else:
                    c.pop("extra_content", None)
                calls.append(c)
            out.append({**m, "tool_calls": calls})
        return out

    @staticmethod
    def _fail(resp: httpx.Response) -> LLMError:
        try:
            detail = resp.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        hint = {401: f" (is {config.API_KEY_ENV} correct?)", 403: " (key lacks access to this model?)",
                404: " (model id wrong? JIMMY_MODEL)", 410: " (model retired: set JIMMY_MODEL)", 429: " (rate limited)"}.get(resp.status_code, "")
        return LLMError(f"LLM HTTP {resp.status_code}{hint}: {detail}", resp.status_code)

    def _gone(self, resp: httpx.Response, body: dict) -> bool:
        """D43: a retired model (404/410) gives way to the next one, for the rest of
        this client's life, instead of breaking every answer. The tools model falls
        back to the chat model; the chat model to MODEL_FALLBACKS."""
        if resp.status_code not in (404, 410):
            return False
        gone = body["model"]
        self.fallbacks = [m for m in self.fallbacks if m != gone]
        if self.tools_model == gone:
            self.tools_model = None
        if self.model == gone and self.fallbacks:   # D44: on OpenAI one model does both jobs
            self.model = self.fallbacks.pop(0)
        if self.model == gone:
            return False
        print(f"[jimmy] model {body['model']} answered HTTP {resp.status_code}; now using {self.model}",
              file=sys.stderr, flush=True)
        body["model"] = self.model
        return True

    def _message(self, resp: httpx.Response) -> dict:
        """The reply's message. Seen 2026-10-03: a 200 whose body was an error object,
        no `choices`, which crashed the agent. Treated like an empty answer: retried."""
        try:
            return resp.json()["choices"][0]["message"] or {}
        except (ValueError, KeyError, IndexError, TypeError):
            print(f"[jimmy] {self.model} answered 200 without a message: {resp.text[:160]}",
                  file=sys.stderr, flush=True)
            return {}

    @staticmethod
    def _usage(resp: httpx.Response) -> dict:
        """Prompt tokens and how many came from the provider's prompt cache (D47)."""
        try:
            u = resp.json().get("usage") or {}
        except Exception:
            return {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        return {k: v for k, v in (("prompt", u.get("prompt_tokens")), ("cached", cached),
                                  ("out", u.get("completion_tokens"))) if v is not None}

    def _chain(self, first: str | None = None) -> list[str]:
        """D54: this provider's models to try in turn before the backup, one try each: the
        one asked for, then the fallbacks (Gemini 3.8 overloaded -> 3.5 Flash-Lite).
        Gemini without a backup too (an overloaded model is usual on its free tier); other
        providers without one: just the one (D43's 404/410 fallbacks work as before)."""
        first = first or self.model
        models = list(dict.fromkeys([first, *self.fallbacks])) if self.backup is not None or self.gemini else [first]
        if self.backup is None:
            return models                              # nobody else to ask: try them all
        # A model that just failed rests, so each request doesn't wait out its deadline
        # again (2026-11-01: 6 s on an overloaded 3.8 before every answer from 3.5).
        now = time.time()
        return [m for m in models if self._model_down.get(m, 0) <= now]

    def _failed(self, model: str, exc: LLMError) -> None:
        if self.backup is not None:
            daily = exc.status == 429 and any(w in str(exc).lower() for w in ("perday", "per day", "daily"))
            self._model_down[model] = time.time() + (_pacific_midnight_in() if daily else config.BACKUP_RETRY_S)
            print(f"[jimmy] {model} failed ({str(exc)[:80]!r}); trying the next", file=sys.stderr, flush=True)

    def _tries(self) -> int:
        """With a backup a failing model isn't retried; the next one is asked (D54)."""
        return 1 if self.backup is not None else self.attempts

    def _deadline(self, stream: bool) -> dict:
        """D54: with a backup, a model that is only slow gives way too. On 2026-11-01 the
        free tier's gemini-3.8-flash took 25-107 s or timed out; Jimmy must not go silent
        that long. The first word within GEMINI_FIRST_WORD_S; a whole answer within
        GEMINI_ANSWER_S. Without a backup, the client's own timeout."""
        if self.backup is None:
            return {}
        return {"timeout": httpx.Timeout(config.GEMINI_FIRST_WORD_S if stream else config.GEMINI_ANSWER_S,
                                         connect=config.CONNECT_TIMEOUT_S)}

    def _first_that_speaks(self, tries: list, other) -> Iterator[str]:
        """D54: each way to answer in turn; the first that says a word keeps the floor and
        never switches mid-sentence; if none does, the backup (`other`) answers."""
        last = None
        for model, make in tries:
            sent = False
            try:
                for piece in make():
                    sent = True
                    yield piece
                return
            except LLMError as exc:
                if sent:
                    raise
                last = exc
                self._failed(model, exc)
        last = last or LLMError("every model of this provider is resting", 503)
        if not self._trip(last):
            raise last
        yield from other()

    def _require_key(self) -> None:
        if not self.configured:
            raise LLMError(f"no API key: set {config.API_KEY_ENV}")

    def chat(self, messages: list[dict], *, max_tokens: int = config.MAX_TOKENS,
             temperature: float = config.TEMPERATURE, thinking: bool | None = None) -> str:
        """The whole answer at once. `thinking` overrides config.THINKING for this call."""
        if (b := self._route()) is not None:
            return b.chat(messages, max_tokens=max_tokens, temperature=temperature, thinking=thinking)
        self._require_key()
        body, last = self._body(messages, False, max_tokens, temperature, thinking), None
        for m in self._chain():
            try:
                return self._once({**body, "model": m})
            except LLMError as exc:
                last = exc
                self._failed(m, exc)
        last = last or LLMError("every model of this provider is resting", 503)
        if not self._trip(last):
            raise last
        return self.backup.chat(messages, max_tokens=max_tokens, temperature=temperature, thinking=thinking)

    def tool_fallback(self) -> str | None:
        """D45: the second model an agent step asks when the first is too slow: the
        next fallback, else the chat model; None if there's no other."""
        first = self.tools_model or self.model
        return next((m for m in (*self.fallbacks, self.model) if m and m != first), None)

    def tool_fallbacks(self) -> list[str]:
        """D51 (A8): every model an agent step may fall back to, in order: the second
        cloud model, then a local one ("local:<name>") when LOCAL_TOOLS_MODEL is set."""
        out = [m for m in (self.tool_fallback(),) if m]
        if self.backup is not None:                   # D54: a slow Gemini step also asks NVIDIA
            out.append("backup:" + (self.backup.tools_model or self.backup.model))
        if config.LOCAL_TOOLS_MODEL and self.base_url == config.BASE_URL.rstrip("/"):
            out.append("local:" + config.LOCAL_TOOLS_MODEL)
        return out

    def chat_tools(self, messages: list[dict], tools: list[dict], *, max_tokens: int = 500,
                   temperature: float = 0.0, model: str | None = None) -> dict:
        """D42: one step of the agent. The model's message, with `tool_calls` (OpenAI
        format) or `content`. Thinking off: measured on nemotron-3-super with it on,
        tool calls came back empty; off, 0.5-1.8 s and a sensible first step.
        `model` (D45): this step on another model (tool_fallback), when the first is slow."""
        if model and model.startswith("local:"):
            name = model.removeprefix("local:")       # D51: the step on local Ollama
            local = _LOCAL_TOOLS.get(name) or _LOCAL_TOOLS.setdefault(name, local_llm(name))
            return local.chat_tools(messages, tools, max_tokens=max_tokens, temperature=temperature, model=name)
        if model and model.startswith("backup:") and self.backup is not None:
            return self.backup.chat_tools(messages, tools, max_tokens=max_tokens, temperature=temperature,
                                          model=model.removeprefix("backup:"))
        if (b := self._route()) is not None:
            return b.chat_tools(messages, tools, max_tokens=max_tokens, temperature=temperature)
        self._require_key()
        last = None
        for m in self._chain(model or self.tools_model or self.model):
            try:
                return self._tools_once(messages, tools, max_tokens, temperature, m)
            except LLMError as exc:
                last = exc
                self._failed(m, exc)
        last = last or LLMError("every model of this provider is resting", 503)
        if not self._trip(last):
            raise last
        return self.backup.chat_tools(messages, tools, max_tokens=max_tokens, temperature=temperature)

    def _tools_once(self, messages, tools, max_tokens, temperature, model) -> dict:
        body = {**self._body(messages, False, max_tokens, temperature, False), "tools": tools, "tool_choice": "auto",
                "model": model or self.tools_model or self.model}
        for attempt in range(self._tries()):
            try:
                resp = self._http().post("/chat/completions", json=body, **self._deadline(False))
            except httpx.HTTPError as exc:
                if attempt == self._tries() - 1:
                    raise LLMError(f"LLM unreachable: {type(exc).__name__}: {exc}") from exc
                time.sleep(config.RETRY_WAIT_S)
                continue
            if resp.status_code in config.RETRY_STATUSES and attempt < self._tries() - 1:
                time.sleep(config.RETRY_WAIT_S)
                continue
            if self._gone(resp, body):
                continue
            if resp.status_code != 200:
                raise self._fail(resp)
            msg = self._message(resp)
            f = ThinkFilter()
            msg["content"] = (f.feed(msg.get("content") or "") + f.flush()).strip()
            if msg.get("tool_calls") or msg["content"]:
                msg["_usage"] = self._usage(resp)       # D47: tokens and cache hits, for the trace
                return msg
        raise LLMError(EMPTY)

    def chat_stream(self, messages: list[dict], *, max_tokens: int = config.MAX_TOKENS,
                    temperature: float = config.TEMPERATURE) -> Iterator[str]:
        """The answer token by token. A plain function, not a generator, so a
        missing key raises here rather than on first iteration."""
        if (b := self._route()) is not None:
            return b.chat_stream(messages, max_tokens=max_tokens, temperature=temperature)
        self._require_key()
        body = self._body(messages, True, max_tokens, temperature)
        if self.backup is None:
            return self._stream(body)
        tries = [(m, lambda m=m: self._stream({**body, "model": m})) for m in self._chain()]
        return self._first_that_speaks(tries, lambda: self.backup.chat_stream(messages, max_tokens=max_tokens,
                                                                                temperature=temperature))

    def _once(self, body: dict) -> str:
        for attempt in range(self._tries()):
            try:
                resp = self._http().post("/chat/completions", json=body, **self._deadline(False))
            except httpx.HTTPError as exc:
                if attempt == self._tries() - 1:
                    raise LLMError(f"LLM unreachable: {type(exc).__name__}: {exc}") from exc
                time.sleep(config.RETRY_WAIT_S)
                continue
            if resp.status_code in config.RETRY_STATUSES and attempt < self._tries() - 1:
                time.sleep(config.RETRY_WAIT_S)
                continue
            if self._gone(resp, body):
                continue
            if resp.status_code != 200:
                raise self._fail(resp)
            msg = self._message(resp)
            f = ThinkFilter()
            answer = (f.feed(msg.get("content") or "") + f.flush()).strip()
            if answer:
                return answer
            if attempt == self._tries() - 1:
                raise LLMError(EMPTY)
            # Measured: ~1 in 5 calls to the hosted model came back 200 and empty.
        raise LLMError("LLM retry exhausted")

    def _stream(self, body: dict) -> Iterator[str]:
        f = ThinkFilter()
        sent = False  # once text has reached the user, a retry would repeat it
        for attempt in range(self._tries()):
            try:
                with self._http().stream("POST", "/chat/completions", json=body, **self._deadline(True)) as resp:
                    if resp.status_code in config.RETRY_STATUSES and attempt < self._tries() - 1:
                        time.sleep(config.RETRY_WAIT_S)
                        continue
                    if self._gone(resp, body):
                        continue
                    if resp.status_code != 200:
                        raise self._fail(resp)
                    for line in resp.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            choice = json.loads(data)["choices"][0]
                        except (ValueError, KeyError, IndexError):
                            continue
                        # `reasoning_content` deltas are deliberately ignored.
                        text = f.feed((choice.get("delta") or {}).get("content") or "")
                        if text:
                            sent = True
                            yield text
                    tail = f.flush()
                    if tail:
                        sent = True
                        yield tail
                    if sent:
                        return
                    if attempt == self._tries() - 1:
                        raise LLMError(EMPTY)
                    # An empty answer: nothing reached the screen, so retrying is safe.
            except httpx.HTTPError as exc:
                if attempt == self._tries() - 1 or sent:
                    raise LLMError(f"LLM stream broke: {type(exc).__name__}: {exc}") from exc
                time.sleep(config.RETRY_WAIT_S)
        raise LLMError("LLM retry exhausted")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def local_llm(model: str | None = None) -> LLM:
    """The same client pointed at local Ollama. Ollama ignores the key."""
    return LLM(key="ollama", model=model or config.LOCAL_MODEL, base_url=config.LOCAL_BASE_URL)


_EMBEDDERS: dict[str, LLM] = {}
_LOCAL_TOOLS: dict[str, LLM] = {}      # D51: local tool-step clients, one per model, kept open


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Meaning-vectors for `texts` from the local embedding model (Stage 5, D24).
    The same client class, pointed at Ollama; raises LLMError if it's unreachable.

    D38: one client per model, kept open (a new one per call paid the connection
    every time), on Ollama's own endpoint so the model can be asked to stay loaded."""
    if not texts:
        return []
    name = model or config.EMBED_MODEL
    client = _EMBEDDERS.get(name) or _EMBEDDERS.setdefault(name, local_llm(name))
    root = client.base_url.removesuffix("/v1")
    try:
        # Its own timeout: the first call loads ~1.2 GB into VRAM, and a batch of
        # chunks is slower than a chat reply (a 60 s limit timed out on first use).
        resp = client._http().post(f"{root}/api/embed",
                                   json={"model": client.model, "input": texts,
                                         "keep_alive": config.EMBED_KEEP_ALIVE,
                                         # D50 (P6): the GPU left to Whisper and the cards model
                                         **({"options": {"num_gpu": 0}} if config.EMBED_ON_CPU else {})},
                                   timeout=httpx.Timeout(300, connect=5))
        if resp.status_code != 200:
            raise LLMError(f"embeddings HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()["embeddings"]
    except httpx.HTTPError as exc:
        raise LLMError(f"embedding model unreachable: {type(exc).__name__}: {exc}") from exc


def unload_local(models: list[str] | None = None) -> list[str]:
    """D50 (P6): ask local Ollama to drop models from VRAM now (keep_alive 0). Returns the
    ones it confirmed; the next use reloads them. Whisper isn't Ollama's and stays."""
    names = models or [config.LOCAL_MODEL, config.EMBED_MODEL]
    client = _EMBEDDERS.get(config.EMBED_MODEL) or _EMBEDDERS.setdefault(config.EMBED_MODEL,
                                                                       local_llm(config.EMBED_MODEL))
    root = client.base_url.removesuffix("/v1")
    done = []
    for name in names:
        try:
            r = client._http().post(f"{root}/api/generate", json={"model": name, "keep_alive": 0},
                                    timeout=httpx.Timeout(10, connect=2))
            if r.status_code == 200:
                done.append(name)
        except httpx.HTTPError:
            pass
    return done
