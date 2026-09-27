"""Crowd reports for everything except floods: accident, power cut, water cut,
blocked road, fire/smoke, health, crowding.

One report = low confidence "warning". Reports of the same type within 500 m and
2 h merge into one event whose confidence grows with each independent report:
  1 report -> 0.35 | 2 -> 0.6 | 3+ -> 0.8     (severity rises to "danger" at 3+ for
  accident/road/fire, because corroborated blockages should reroute people).
Anyone can later vote "still there" / "gone" on the event (see /api/hazards/{id}/vote).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import store, trace
from app.geo import haversine_m
from app.models import HazardEvent, utcnow
from app.reports import trust

router = APIRouter(prefix="/api/reports", tags=["reports"])

LABELS = {
    "accident": "Accident reported", "water": "Water cut reported",
    "road": "Road blocked", "fire": "Fire or smoke reported", "health": "Health emergency nearby",
    "crowd": "Very crowded / unrest", "other": "Problem reported",
}
ESCALATE = {"accident", "road", "fire"}
RADIUS = {"power": 1500, "water": 1500}


class CrowdReport(BaseModel):
    type: str
    lat: float
    lon: float
    note: str = ""
    device_id: str = "anon"
    accuracy_m: float | None = None


def confidence_for(n: int) -> float:
    return 0.35 if n == 1 else 0.6 if n == 2 else 0.8


@router.post("")
def create_report(r: CrowdReport):
    if r.type not in LABELS:
        raise HTTPException(400, f"type must be one of {list(LABELS)}")
    with trace.span("report", f"Crowd report: {r.type}", lat=round(r.lat, 4), lon=round(r.lon, 4),
                    device=r.device_id[:8], accuracy_m=r.accuracy_m) as t:
        ev = ingest(r)
        t.set(event_id=ev.id, confidence=ev.confidence, severity=ev.severity, reports=ev.reports_count)
        return ev


def ingest(r: CrowdReport, simulated: bool = False) -> HazardEvent:
    """Shared by the API and the simulation lab (fake devices, same rules)."""
    ok, why = trust.allow(r.device_id, r.type)
    if not ok:
        trace.step("Rejected by rate limit", reason=why)
        raise HTTPException(429, why)
    trust.record(r.device_id, r.type)
    now = utcnow()
    match = None
    for e in store.active([r.type]):
        if e.source == "crowd" and e.is_simulated == simulated and haversine_m(r.lat, r.lon, e.lat, e.lon) < 500 \
                and now - e.observed_at < timedelta(hours=2):
            match = e
            break
    if match and r.device_id in match.data.get("devices", []):
        trace.step("Same device already reported this: one device = one voice", event=match.id)
        return match  # same phone again: one device = one voice
    if match:
        n = match.reports_count + 1
        sev = "danger" if (n >= 3 and r.type in ESCALATE) else match.severity
        trace.step(f"Merged into {match.id}: {n} distinct devices within 500 m / 2 h",
                   confidence_rule="1 report 0.35 | 2 -> 0.6 | 3+ -> 0.8",
                   confidence=max(match.confidence, confidence_for(n)),
                   severity=sev, escalated=sev != match.severity,
                   status_now="avoid" if sev in ("danger", "critical") and confidence_for(n) >= 0.5 else "caution")
        ev = match.model_copy(update={
            "reports_count": n, "observed_at": now, "expires_at": None,
            "confidence": max(match.confidence, confidence_for(n)),
            "severity": sev,
            "lat": (match.lat * (n - 1) + r.lat) / n, "lon": (match.lon * (n - 1) + r.lon) / n,
            "title": f"{LABELS[r.type]} ({n} people)",
            "data": {**match.data, "devices": match.data.get("devices", []) + [r.device_id], "notes": (match.data.get("notes", []) + [r.note])[-5:] if r.note else match.data.get("notes", [])},
        })
    else:
        conf = round(confidence_for(1) * trust.gps_factor(r.accuracy_m), 2)
        trace.step("New crowd event (no matching report within 500 m / 2 h)",
                   confidence=f"0.35 x gps_factor {trust.gps_factor(r.accuracy_m)} = {conf}",
                   status_now="caution (a single unverified report can never cause 'avoid')")
        ev = HazardEvent(type=r.type, severity="warning", title=LABELS[r.type],
                         description="Reported by a traveller/local. Unverified until confirmed by others.",
                         lat=r.lat, lon=r.lon, radius_m=RADIUS.get(r.type, 300), is_simulated=simulated,
                         confidence=conf, source="crowd",
                         data={"notes": [r.note] if r.note else [], "devices": [r.device_id]})
    return store.upsert(ev)
