"""Power-cut reporting that is actually reliable (the utility gives no warning).

Signals, strongest first:
  1. CHARGER CHECK (automatic, Android/Chrome): the user says their phone is plugged
     into a wall socket; the app reads the Battery API. Plugged in but NOT charging
     = the socket is dead. Confidence 0.6 for a single device.
  2. POWER WATCH (opt-in): while the app is open and the phone is charging, a sudden
     stop in charging pops "Did the power just go out?" -> one tap. Catches cuts
     the second they happen.
  3. Plain tap "power is out here" (iPhone/any): confidence 0.4.

Aggregation: reports are bucketed into ~500 m grid cells. A cell's outage confidence
grows with DISTINCT devices in the last 45 min: 1 -> 0.4 (0.6 charger-verified),
2 -> 0.65, 3+ -> 0.85. "Power is back" taps from 2 devices (or half the reporters)
close the outage and write it to history.

History turns into something the utility never publishes: per-area outage stats
(cuts in the last 30 days, typical duration, usual hours) -> GET /api/power/history.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import config, store, trace
from app.models import HazardEvent, utcnow
from app.reports import trust

router = APIRouter(prefix="/api/power", tags=["power"])
CELL = 0.005                      # ~500 m
WINDOW = timedelta(minutes=45)
HISTORY_FILE = config.DATA_DIR / "power_history.json"

_cells: dict[str, dict] = {}      # cell -> {off: {device: (ts, verified)}, on: {device: ts}, since, lat, lon}


def _cell(lat, lon) -> tuple[str, float, float]:
    clat, clon = round(lat / CELL) * CELL, round(lon / CELL) * CELL
    return f"{clat:.3f},{clon:.3f}", clat, clon


def _history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_history(h: list[dict]) -> None:
    try:
        HISTORY_FILE.write_text(json.dumps(h[-5000:]), encoding="utf-8")
    except Exception:
        pass


class PowerReport(BaseModel):
    lat: float
    lon: float
    status: str = "off"                   # "off" | "on" (power is back)
    device_id: str = "anon"
    accuracy_m: float | None = None
    charger_verified: bool = False        # plugged in + Battery API says not charging
    source: str = "tap"                   # "tap" | "charger" | "watch"


def _publish(key: str) -> HazardEvent | None:
    c = _cells[key]
    now = utcnow()
    offs = {d: v for d, v in c["off"].items() if now - v[0] < WINDOW}
    c["off"] = offs
    if not offs:
        store.remove(f"power-{key}")
        return None
    n = len(offs)
    verified = sum(1 for _, v in offs.values() if v)
    conf = 0.85 if n >= 3 else 0.65 if n == 2 else (0.6 if verified else 0.4)
    since = c["since"]
    trace.step(f"Power cell {key}: {n} device(s) in the last 45 min, {verified} charger-verified",
               rule="1 -> 0.4 (0.6 charger-verified) | 2 -> 0.65 | 3+ -> 0.85", confidence=conf)
    return store.upsert(HazardEvent(
        id=f"power-{key}", type="power", severity="warning",
        title=f"Power cut · {n} report{'s' if n > 1 else ''}" + (" · charger-verified" if verified else ""),
        description=f"No electricity reported here since {since:%H:%M} UTC. "
                    "Expect no lights, lifts, card machines or AC; phone signal may weaken.",
        lat=c["lat"], lon=c["lon"], radius_m=400, confidence=conf, source="crowd",
        is_simulated=c.get("sim", False),
        observed_at=max(v[0] for v in offs.values()), expires_at=now + timedelta(hours=3),
        reports_count=n, data={"since": since.isoformat(), "devices": n, "charger_verified": verified,
                                "cell": key}))


@router.post("/report")
def report(r: PowerReport):
    with trace.span("report", f"Power report: {r.status}", source=r.source, charger_verified=r.charger_verified,
                    lat=round(r.lat, 4), lon=round(r.lon, 4)) as t:
        out = ingest(r)
        t.set(**{k: v for k, v in out.items() if k != "event"})
        return out


def ingest(r: PowerReport, simulated: bool = False) -> dict:
    ok, why = trust.allow(r.device_id, f"power-{r.status}")
    if not ok:
        raise HTTPException(429, why)
    trust.record(r.device_id, f"power-{r.status}")
    key, clat, clon = _cell(r.lat, r.lon)
    if simulated:
        key = f"sim-{key}"   # simulated devices never mix with real reports
    now = utcnow()
    c = _cells.setdefault(key, {"off": {}, "on": {}, "since": now, "lat": clat, "lon": clon, "sim": simulated})

    if r.status == "off":
        if not c["off"]:
            c["since"], c["on"] = now, {}
        c["off"][r.device_id] = (now, r.charger_verified)
        return {"accepted": True, "event": _publish(key)}

    # power is back
    c["on"][r.device_id] = now
    reporters = len(c["off"])
    if reporters and (len(c["on"]) >= 2 or len(c["on"]) * 2 >= reporters):
        h = _history()
        h.append({"cell": key, "lat": clat, "lon": clon, "start": c["since"].isoformat(),
                  "end": now.isoformat(), "minutes": round((now - c["since"]).total_seconds() / 60),
                  "devices": reporters})
        if not c.get("sim"):
            _save_history(h)
        trace.step("Outage closed: 'power is back' from 2 devices (or half the reporters)",
                   minutes=round((now - c["since"]).total_seconds() / 60), written_to_history=not c.get("sim"))
        for d in c["off"]:
            trust.reward(d, 0.05)   # their report was confirmed by the "back on" reports
        _cells.pop(key)
        store.remove(f"power-{key}")
        return {"accepted": True, "closed": True}
    return {"accepted": True, "closed": False, "event": _publish(key) if c["off"] else None}


@router.get("/history")
def history(lat: float, lon: float, days: int = 30, radius_cells: int = 2):
    """Outage stats around a place — what the utility never tells you."""
    key, clat, clon = _cell(lat, lon)
    since = utcnow() - timedelta(days=days)
    near = [x for x in _history()
            if abs(x["lat"] - clat) <= radius_cells * CELL + 1e-9 and abs(x["lon"] - clon) <= radius_cells * CELL + 1e-9
            and datetime.fromisoformat(x["start"]) >= since]
    if not near:
        return {"cuts": 0, "days": days, "summary": f"No power cuts reported nearby in the last {days} days."}
    mins = sorted(x["minutes"] for x in near)
    hours = [datetime.fromisoformat(x["start"]).hour for x in near]
    common = max(set(hours), key=hours.count)
    return {"cuts": len(near), "days": days, "median_minutes": mins[len(mins) // 2],
            "longest_minutes": mins[-1], "usual_start_hour_utc": common,
            "last_cut": max(x["start"] for x in near),
            "summary": f"{len(near)} power cut(s) reported nearby in {days} days, "
                       f"typically ~{mins[len(mins) // 2]} min, often around {common:02d}:00 UTC."}


def clear_simulated() -> int:
    keys = [k for k, c in _cells.items() if c.get("sim")]
    for k in keys:
        _cells.pop(k, None)
        store.remove(f"power-{k}")
    return len(keys)
