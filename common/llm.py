"""Thin wrapper around the Google Gemini SDK shared by all three solutions.

Free-tier keys have small per-model daily quotas, and Google retires model names over time.
So `get_client()` returns a client whose generate_content() automatically falls back to the
next model in MODEL_CHAIN when a model is unavailable (404) or its daily quota is exhausted (429).
"""
from __future__ import annotations

import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DEFAULT_MODEL = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash-lite"
FALLBACKS = ["gemini-3.8-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash-lite",
             "gemini-3-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-3.8-flash"]
MODEL_CHAIN = list(dict.fromkeys([DEFAULT_MODEL] + FALLBACKS))
_dead: set[str] = set()   # models that returned 404 / daily-quota-exhausted this process


def _is_switch_error(msg: str) -> bool:
    if "404" in msg or "NOT_FOUND" in msg:
        return True
    # daily quota exhausted -> retrying in seconds won't help, move on to another model
    return "RESOURCE_EXHAUSTED" in msg and ("PerDay" in msg or re.search(r"retry in \d+h", msg) is not None)


class _Models:
    def __init__(self, raw):
        self.raw = raw

    def generate_content(self, model=None, **kw):
        last = None
        for m in MODEL_CHAIN:
            if m in _dead:
                continue
            try:
                return self.raw.models.generate_content(model=m, **kw)
            except Exception as e:  # noqa: BLE001
                if _is_switch_error(str(e)):
                    print(f"  [llm] {m} unavailable ({str(e)[:60]}...) -> trying next model")
                    _dead.add(m)
                    last = e
                    continue
                raise
        raise RuntimeError(f"All Gemini models unavailable or out of quota: {last}")


class _Client:
    def __init__(self, raw):
        self.models = _Models(raw)


def get_client() -> _Client:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key "
            "(free at https://aistudio.google.com/apikey)."
        )
    return _Client(genai.Client(api_key=key))


def with_retry(fn, *args, retries: int = 4, **kwargs):
    """Call fn with exponential backoff on per-minute rate limits / transient server errors."""
    delay = 5
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            transient = any(s in msg for s in ("429", "503", "500", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "overloaded"))
            if not transient or attempt == retries or msg.startswith("All Gemini models"):
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60)


__all__ = ["genai", "types", "get_client", "with_retry", "DEFAULT_MODEL"]
