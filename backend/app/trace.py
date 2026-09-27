"""Under-the-hood traces (testing tool).

Every calculation, agent step, AI call and external API call records a *span*:
{id, kind, title, at, ms, ok, data, steps[{t_ms, label, data}], parent}
so the app's "Under the hood" panel can show WHAT happened and WHY, live.

    with trace.span("calc", "Recommend places", lat=..., lon=...) as t:
        t.step("Scored candidate", name=..., score=...)

Spans nest through a context variable: an AI call made inside a recommendation shows
up as its own span AND as a linked step of its parent. Only finished spans are published.
Cheap enough to leave on; the panel is hidden when DEV_MODE=0.
"""
from __future__ import annotations

import asyncio
import contextvars
import itertools
import time
from collections import deque
from datetime import date, datetime, timezone

TRACES: deque = deque(maxlen=500)
_subs: set[asyncio.Queue] = set()
_current: contextvars.ContextVar = contextvars.ContextVar("rafiq_span", default=None)
_ids = itertools.count(1)
MAX_STR = 1600
MAX_LIST = 60


def safe(v, depth: int = 0):
    """Make anything JSON-friendly and small (datetimes, pydantic models, long text, big lists)."""
    if depth > 6:
        return "…"
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, str):
        return v if len(v) <= MAX_STR else v[:MAX_STR] + f"… (+{len(v) - MAX_STR} chars)"
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "model_dump"):
        return safe(v.model_dump(mode="json"), depth + 1)
    if isinstance(v, dict):
        return {str(k): safe(x, depth + 1) for k, x in list(v.items())[:MAX_LIST]}
    if isinstance(v, (list, tuple, set)):
        items = list(v)
        out = [safe(x, depth + 1) for x in items[:MAX_LIST]]
        if len(items) > MAX_LIST:
            out.append(f"… +{len(items) - MAX_LIST} more")
        return out
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    return str(v)[:MAX_STR]


def _publish(rec: dict) -> None:
    TRACES.appendleft(rec)
    for q in list(_subs):
        try:
            q.put_nowait(rec)
        except asyncio.QueueFull:
            pass


class Span:
    def __init__(self, kind: str, title: str, /, **data):
        parent = _current.get()
        self.rec = {"id": next(_ids), "kind": kind, "title": title,
                    "at": datetime.now(timezone.utc).isoformat(), "ms": None, "ok": True,
                    "data": safe(data), "steps": [], "parent": parent.rec["id"] if parent else None}
        self.parent = parent
        self._t0 = time.perf_counter()
        self._token = None

    def step(self, label: str, /, **data) -> "Span":
        self.rec["steps"].append({"t_ms": round((time.perf_counter() - self._t0) * 1000),
                                  "label": label, "data": safe(data) if data else None})
        return self

    def set(self, **data) -> "Span":
        self.rec["data"].update(safe(data))
        return self

    def fail(self, reason: str) -> "Span":
        self.rec["ok"] = False
        self.rec["data"]["error"] = safe(reason)
        return self

    def end(self) -> dict:
        if self.rec["ms"] is None:
            self.rec["ms"] = round((time.perf_counter() - self._t0) * 1000)
            _publish(self.rec)
            if self.parent:
                self.parent.step(f"-> {self.rec['kind']}: {self.rec['title']}",
                                 ref=self.rec["id"], ms=self.rec["ms"], ok=self.rec["ok"])
        return self.rec

    def __enter__(self) -> "Span":
        self._token = _current.set(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.fail(f"{exc_type.__name__}: {exc}")
        if self._token is not None:
            _current.reset(self._token)
        self.end()
        return False


def span(kind: str, title: str, /, **data) -> Span:
    return Span(kind, title, **data)


def step(label: str, /, **data) -> None:
    """Add a step to whatever span is running (no-op outside a span)."""
    cur = _current.get()
    if cur:
        cur.step(label, **data)


def event(kind: str, title: str, /, ok: bool = True, **data) -> dict:
    s = Span(kind, title, **data)
    if not ok:
        s.rec["ok"] = False
    s.rec["ms"] = 0
    _publish(s.rec)
    if s.parent:
        s.parent.step(f"-> {kind}: {title}", ref=s.rec["id"])
    return s.rec


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subs.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subs.discard(q)


def recent(kind: str | None = None, limit: int = 200) -> list[dict]:
    return [t for t in TRACES if not kind or t["kind"] == kind][:limit]


def clear() -> None:
    TRACES.clear()
