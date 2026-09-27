"""One tiny client for every AI call (NVIDIA NIM by default; any OpenAI-compatible API works).
Every function returns None on failure — callers ALWAYS have a non-AI fallback.

Reliability: each call tries the configured model, then the fallback models, in order.
A model that times out or is gone (404/410) is skipped for 5 minutes (circuit breaker),
so one overloaded model never freezes the app. Every call is recorded as an "llm" trace.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx

from app import config, trace

log = logging.getLogger("llm")
_down_until: dict[str, float] = {}   # model -> time it may be retried
COOLDOWN_S = 300
LAST_OK: dict[str, dict] = {}        # "text"|"vision" -> {model, at, ms}  (shown in /api/health)


def available() -> bool:
    return bool(config.LLM_API_KEY)


def _chain(model: str | None, vision: bool) -> list[str]:
    first = model or (config.VISION_MODEL if vision else config.LLM_MODEL)
    rest = config.VISION_FALLBACK_MODELS if vision else config.LLM_FALLBACK_MODELS
    out = []
    for m in [first, *rest]:
        if m and m not in out:
            out.append(m)
    return out


def _extra(model: str) -> dict:
    # Nemotron 3 models "think" before answering; we want the answer only (faster, no leaks).
    return {"chat_template_kwargs": {"enable_thinking": False}} if "nemotron-3" in model else {}


def _preview(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = [p.get("text") if p.get("type") == "text" else "<image>" for p in c]
        out.append({"role": m.get("role"), "content": c})
    return out


async def chat(messages: list[dict], model: str | None = None, max_tokens: int = 700,
               temperature: float = 0.2, timeout: float | None = None, purpose: str = "chat") -> str | None:
    if not available():
        trace.event("llm", f"{purpose}: skipped (no AI key)", ok=False)
        return None
    vision = any(isinstance(m.get("content"), list) for m in messages)
    with trace.span("llm", purpose, vision=vision, prompt=_preview(messages)) as t:
        for m in _chain(model, vision):
            if _down_until.get(m, 0) > time.time():
                t.step(f"skip {m} (cooling down after a failure)")
                continue
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=timeout or config.LLM_TIMEOUT_S) as c:
                    for attempt in (1, 2):   # busy (429/5xx): one quick retry before the next model
                        r = await c.post(f"{config.LLM_BASE_URL}/chat/completions",
                                         headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                                         json={"model": m, "messages": messages, "max_tokens": max_tokens,
                                               "temperature": temperature, **_extra(m)})
                        if r.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                            t.step(f"{m}: HTTP {r.status_code}, retrying once")
                            await asyncio.sleep(1.5)
                            continue
                        break
                ms = round((time.perf_counter() - t0) * 1000)
                if r.status_code in (404, 410):
                    _down_until[m] = time.time() + COOLDOWN_S * 12
                    t.step(f"{m}: HTTP {r.status_code} (model unavailable)", ms=ms)
                    continue
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                LAST_OK["vision" if vision else "text"] = {"model": m, "at": time.time(), "ms": ms}
                t.step(f"{m}: answered", ms=ms)
                t.set(model=m, output=text)
                return text
            except Exception as exc:
                ms = round((time.perf_counter() - t0) * 1000)
                # timeouts mean "overloaded for a while"; a server error is often a blip
                _down_until[m] = time.time() + (COOLDOWN_S if isinstance(exc, httpx.TimeoutException) else 60)
                t.step(f"{m}: failed ({type(exc).__name__})", ms=ms, error=str(exc)[:200])
                log.warning("LLM %s failed: %s", m, exc)
        t.fail("every model failed; caller uses its non-AI fallback")
        return None


def extract_json(text: str | None):
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


async def chat_json(system: str, user, model: str | None = None, max_tokens: int = 900,
                    purpose: str = "chat_json"):
    """user can be a string or a list of content parts (for images)."""
    text = await chat([{"role": "system", "content": system + "\nReply with JSON only."},
                       {"role": "user", "content": user}], model=model, max_tokens=max_tokens, purpose=purpose)
    out = extract_json(text)
    if text is not None and out is None:
        trace.event("llm", f"{purpose}: answer was not valid JSON", ok=False, raw=text)
    return out
