"""Hazard event store + live pub/sub (feeds the SSE stream).

In-memory for the hackathon; the public functions are the only interface, so
swapping to SQLite/Postgres later touches this file only.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from app.geo import haversine_m, point_segment_m
from app.models import SEVERITY_RANK, HazardEvent, utcnow

DEFAULT_TTL_MIN = {
    "flood": 180, "fire": 360, "power": 240, "water": 720, "storm": 180, "wind": 180,
    "heat": 480, "earthquake": 720, "accident": 120, "road": 360, "health": 240,
    "crowd": 120, "other": 180,
}

_events: dict[str, HazardEvent] = {}
_subscribers: set[asyncio.Queue] = set()


# ── pub/sub ─────────────────────────────────────────────────────────────────
def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def _notify(kind: str, payload: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait({"kind": kind, **payload})
        except asyncio.QueueFull:
            pass  # slow client: it will resync on next full refresh


# ── writes ──────────────────────────────────────────────────────────────────
def upsert(event: HazardEvent) -> HazardEvent:
    if event.expires_at is None:
        event.expires_at = event.observed_at + timedelta(minutes=DEFAULT_TTL_MIN.get(event.type, 180))
    old = _events.get(event.id)
    if old:  # keep community votes across refreshes of the same event
        event.votes_still_there, event.votes_gone = old.votes_still_there, old.votes_gone
    _events[event.id] = event
    _notify("upsert", {"event": event.model_dump(mode="json")})
    return event


def remove(event_id: str) -> bool:
    if _events.pop(event_id, None) is None:
        return False
    _notify("remove", {"id": event_id})
    return True


def replace_source(source: str, events: list[HazardEvent]) -> None:
    """A collector publishes its full current picture; stale ones from that source disappear.
    Simulated events are never touched by real collectors (the simulation lab reuses source names)."""
    keep = {e.id for e in events}
    for eid in [e.id for e in _events.values() if e.source == source and not e.is_simulated and e.id not in keep]:
        remove(eid)
    for e in events:
        upsert(e)


def vote(event_id: str, still_there: bool) -> HazardEvent | None:
    e = _events.get(event_id)
    if not e:
        return None
    from app import trace
    before = e.confidence
    if still_there:
        e.votes_still_there += 1
        e.confidence = min(0.95, e.confidence + 0.1)
        e.expires_at = max(e.expires_at, utcnow() + timedelta(minutes=60))
    else:
        e.votes_gone += 1
        e.confidence = max(0.05, e.confidence - 0.15)
        if e.votes_gone >= 3 and e.votes_gone > e.votes_still_there:
            remove(event_id)
            trace.event("calc", f"Vote 'gone' removed {e.title}", votes_gone=e.votes_gone,
                        votes_still_there=e.votes_still_there, rule="removed at 3+ 'gone' votes outnumbering 'still there'")
            return e
    trace.event("calc", f"Vote '{'still there' if still_there else 'gone'}': {e.title}",
                confidence=f"{before:.2f} -> {e.confidence:.2f}", rule="still there +0.10 (max 0.95), gone -0.15 (min 0.05)",
                votes_still_there=e.votes_still_there, votes_gone=e.votes_gone)
    _notify("upsert", {"event": e.model_dump(mode="json")})
    return e


def clear(simulated_only: bool = True) -> int:
    ids = [e.id for e in _events.values() if e.is_simulated or not simulated_only]
    for i in ids:
        remove(i)
    return len(ids)


# ── reads ───────────────────────────────────────────────────────────────────
def active(types: list[str] | None = None) -> list[HazardEvent]:
    now = utcnow()
    for eid in [e.id for e in _events.values() if e.expires_at and e.expires_at < now]:
        remove(eid)
    out = [e for e in _events.values() if not types or e.type in types]
    return sorted(out, key=lambda e: (-SEVERITY_RANK[e.severity], -e.confidence))


def get(event_id: str) -> HazardEvent | None:
    return _events.get(event_id)


def status_of(events: list[HazardEvent]) -> str:
    """clear | caution | avoid.  Low-confidence events can only ever cause 'caution'."""
    worst = "clear"
    for e in events:
        r = SEVERITY_RANK[e.severity]
        if r >= 2 and e.confidence >= 0.5:
            return "avoid"
        if r >= 1:
            worst = "caution"
    return worst


def near(lat: float, lon: float, radius_m: float) -> list[dict]:
    hits = []
    for e in active():
        d = haversine_m(lat, lon, e.lat, e.lon)
        if d <= radius_m + e.radius_m:
            hits.append({"distance_m": round(d), "event": e})
    hits.sort(key=lambda h: (-SEVERITY_RANK[h["event"].severity], h["distance_m"]))
    return hits


def along_route(coords: list[list[float]], buffer_m: float = 250) -> dict:
    """Hazards within buffer of a polyline, ordered by km along the route."""
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine_m(*coords[i - 1], *coords[i]))
    step = max(1, len(coords) // 400)  # long routes: sample for speed
    idx = list(range(0, len(coords), step))
    if idx[-1] != len(coords) - 1:
        idx.append(len(coords) - 1)
    hits = []
    for e in active():
        best, best_i = float("inf"), 0
        for a, b in zip(idx, idx[1:]):
            d = point_segment_m(e.lat, e.lon, coords[a], coords[b])
            if d < best:
                best, best_i = d, a
        if best <= e.radius_m + buffer_m:
            hits.append({"event": e, "distance_to_route_m": round(best),
                         "km_along_route": round(cum[best_i] / 1000, 1)})
    hits.sort(key=lambda h: h["km_along_route"])
    return {"status": status_of([h["event"] for h in hits]), "hits": hits,
            "route_km": round(cum[-1] / 1000, 1)}
