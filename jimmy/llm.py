"""The one LLM client in this repo (D14). Nothing else may talk to a model API.

OpenAI-compatible chat completions against NVIDIA's endpoint. One httpx client
is kept open and reused, so every call after the first skips the TCP + TLS
handshake (D15). Responses can stream token by token.
"""
from __future__ import annotations

import json
import os
import time
from typing import Iterator

import httpx

from . import config


class LLMError(RuntimeError):
    pass


EMPTY = "the model returned an empty answer twice; try again"


def api_key() -> str | None:
    """The key from the environment, or from the user's registry environment.

    `setx` writes HKCU\\Environment but only new processes see it; reading the
    registry too means a key set a minute ago works without restarting the app.
    """
    key = os.environ.get(config.API_KEY_ENV)
    if key:
        return key.strip()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return (winreg.QueryValueEx(k, config.API_KEY_ENV)[0] or "").strip() or None
    except OSError:
        return None


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
                 base_url: str = config.BASE_URL, transport: httpx.BaseTransport | None = None):
        self.key = key if key is not None else api_key()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self._client: httpx.Client | None = None

    @property
    def configured(self) -> bool:
        return bool(self.key)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url, transport=self._transport,
                headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"},
                timeout=httpx.Timeout(config.READ_TIMEOUT_S, connect=config.CONNECT_TIMEOUT_S))
        return self._client

    def _body(self, messages, stream, max_tokens, temperature, thinking=None) -> dict:
        # Both spellings of the switch: NVIDIA's chat templates differ by model family.
        think = config.THINKING if thinking is None else thinking
        return {"model": self.model, "messages": messages, "stream": stream,
                "max_tokens": max_tokens, "temperature": temperature,
                "chat_template_kwargs": {"enable_thinking": think, "thinking": think}}

    @staticmethod
    def _fail(resp: httpx.Response) -> LLMError:
        try:
            detail = resp.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        hint = {401: " (is NVIDIA_API_KEY correct?)", 403: " (key lacks access to this model?)",
                404: " (model id wrong? JIMMY_MODEL)", 429: " (rate limited)"}.get(resp.status_code, "")
        return LLMError(f"LLM HTTP {resp.status_code}{hint}: {detail}")

    def _require_key(self) -> None:
        if not self.configured:
            raise LLMError(f"no API key: set {config.API_KEY_ENV}")

    def chat(self, messages: list[dict], *, max_tokens: int = config.MAX_TOKENS,
             temperature: float = config.TEMPERATURE, thinking: bool | None = None) -> str:
        """The whole answer at once. `thinking` overrides config.THINKING for this call."""
        self._require_key()
        return self._once(self._body(messages, False, max_tokens, temperature, thinking))

    def chat_stream(self, messages: list[dict], *, max_tokens: int = config.MAX_TOKENS,
                    temperature: float = config.TEMPERATURE) -> Iterator[str]:
        """The answer token by token. A plain function, not a generator, so a
        missing key raises here rather than on first iteration."""
        self._require_key()
        return self._stream(self._body(messages, True, max_tokens, temperature))

    def _once(self, body: dict) -> str:
        for attempt in (0, 1):
            try:
                resp = self._http().post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                if attempt:
                    raise LLMError(f"LLM unreachable: {type(exc).__name__}: {exc}") from exc
                time.sleep(config.RETRY_WAIT_S)
                continue
            if resp.status_code in config.RETRY_STATUSES and not attempt:
                time.sleep(config.RETRY_WAIT_S)
                continue
            if resp.status_code != 200:
                raise self._fail(resp)
            msg = resp.json()["choices"][0]["message"]
            f = ThinkFilter()
            answer = (f.feed(msg.get("content") or "") + f.flush()).strip()
            if answer:
                return answer
            if attempt:
                raise LLMError(EMPTY)
            # Measured: ~1 in 5 calls to the hosted model came back 200 and empty.
        raise LLMError("LLM retry exhausted")

    def _stream(self, body: dict) -> Iterator[str]:
        f = ThinkFilter()
        sent = False  # once text has reached the user, a retry would repeat it
        for attempt in (0, 1):
            try:
                with self._http().stream("POST", "/chat/completions", json=body) as resp:
                    if resp.status_code in config.RETRY_STATUSES and not attempt:
                        time.sleep(config.RETRY_WAIT_S)
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
                    if attempt:
                        raise LLMError(EMPTY)
                    # An empty answer: nothing reached the screen, so retrying is safe.
            except httpx.HTTPError as exc:
                if attempt or sent:
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


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Meaning-vectors for `texts` from the local embedding model (Stage 5, D24).
    The same client class, pointed at Ollama; raises LLMError if it's unreachable."""
    if not texts:
        return []
    client = local_llm(model or config.EMBED_MODEL)
    try:
        # Its own timeout: the first call loads ~1.2 GB into VRAM, and a batch of
        # chunks is slower than a chat reply (a 60 s limit timed out on first use).
        resp = client._http().post("/embeddings", json={"model": client.model, "input": texts},
                                   timeout=httpx.Timeout(300, connect=5))
        if resp.status_code != 200:
            raise LLMError(f"embeddings HTTP {resp.status_code}: {resp.text[:200]}")
        return [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]
    except httpx.HTTPError as exc:
        raise LLMError(f"embedding model unreachable: {type(exc).__name__}: {exc}") from exc
    finally:
        client.close()
