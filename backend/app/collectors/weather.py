"""Weather + river-flood collector (Open-Meteo, free, no key).

For every watched point (destinations + active trip endpoints) it checks the
NEXT 6 HOURS and emits events only when a threshold is crossed:
  rain  (mm/h)            >= 7.5 warning | >= 15 danger | >= 30 critical   -> type "storm"
  wind gusts (km/h)       >= 60 warning  | >= 80 danger | >= 100 critical  -> type "wind"
  feels-like temp (°C)    >= 38 warning  | >= 42 danger | >= 46 critical   -> type "heat"
  river discharge / median (next 3 days, GloFAS)
                          >= 2 warning   | >= 4 danger  | >= 8 critical    -> type "flood"
Thresholds are deliberately simple and documented so judges/users can audit them.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx

from app import trace
from app.models import HazardEvent, utcnow

log = logging.getLogger("weather")

RAIN = [(30, "critical"), (15, "danger"), (7.5, "warning")]
GUST = [(100, "critical"), (80, "danger"), (60, "warning")]
HEAT = [(46, "critical"), (42, "danger"), (38, "warning")]
RIVER = [(8, "critical"), (4, "danger"), (2, "warning")]


def _grade(value, table):
    for limit, sev in table:
        if value is not None and value >= limit:
            return sev
    return None


def events_from_readings(p: dict, rain: float | None = None, gust: float | None = None,
                         feels: float | None = None, now=None, source: str = "open-meteo",
                         simulated: bool = False) -> list[HazardEvent]:
    """Pure threshold logic (also used by the simulation lab with made-up readings)."""
    now = now or utcnow()
    out = []
    for typ, val, table, label, unit in (("storm", rain, RAIN, "Heavy rain", "mm/h"),
                                         ("wind", gust, GUST, "Strong wind gusts", "km/h"),
                                         ("heat", feels, HEAT, "Extreme heat", "°C feels-like")):
        sev = _grade(val, table)
        if sev:
            out.append(HazardEvent(
                id=f"{'sim-' if simulated else ''}wx-{typ}-{p['id']}", type=typ, severity=sev,
                title=f"{label}: up to {val:.0f} {unit}",
                description=f"Forecast for the next 6 hours around {p['name']}.",
                lat=p["lat"], lon=p["lon"], radius_m=8000, confidence=0.75,
                source=source, source_url=None if simulated else "https://open-meteo.com",
                is_simulated=simulated, observed_at=now, expires_at=now + timedelta(hours=2),
                data={"value": val, "unit": unit, "threshold": [lim for lim, s in table if s == sev][0]}))
    return out


def river_event(p: dict, ratio: float, max_q: float, now=None, source: str = "open-meteo-flood",
                simulated: bool = False) -> HazardEvent | None:
    now = now or utcnow()
    sev = _grade(ratio, RIVER)
    if not sev or max_q <= 5:  # ignore tiny streams (< 5 m³/s)
        return None
    return HazardEvent(
        id=f"{'sim-' if simulated else ''}river-{p['id']}", type="flood", severity=sev,
        title=f"River running {ratio:.1f}× its normal level",
        description=f"River discharge forecast near {p['name']} (next 3 days).",
        lat=p["lat"], lon=p["lon"], radius_m=5000, confidence=0.6,
        source=source, source_url=None if simulated else "https://open-meteo.com/en/docs/flood-api",
        is_simulated=simulated, observed_at=now, expires_at=now + timedelta(hours=6),
        data={"discharge_ratio": round(ratio, 1), "kind": "river", "max_discharge_m3s": round(max_q, 1)})


async def collect(points: list[dict]) -> list[HazardEvent]:
    """points: [{id, name, lat, lon}]"""
    if not points:
        return []
    events: list[HazardEvent] = []
    lats = ",".join(str(p["lat"]) for p in points)
    lons = ",".join(str(p["lon"]) for p in points)
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lats, "longitude": lons, "timezone": "UTC", "forecast_hours": 6,
                "hourly": "precipitation,wind_gusts_10m,apparent_temperature"})
            r.raise_for_status()
            data = r.json()
            data = data if isinstance(data, list) else [data]
    except Exception as exc:
        log.warning("open-meteo forecast failed: %s", exc)
        data = []

    now = utcnow()
    notable = []
    for p, d in zip(points, data):
        h = d.get("hourly", {})
        rain, gust, feels = (max([x for x in (h.get(k) or []) if x is not None] or [0]) for k in ("precipitation", "wind_gusts_10m", "apparent_temperature"))
        evs = events_from_readings(p, rain=rain, gust=gust, feels=feels, now=now)
        events += evs
        notable.append({"place": p["name"], "rain_mm_h": rain, "gust_kmh": gust, "feels_c": feels,
                        "events": [e.severity + " " + e.type for e in evs]})
    notable.sort(key=lambda x: -(x["rain_mm_h"] or 0))
    trace.step(f"Open-Meteo forecast for {len(data)} places (next 6 h)",
               thresholds={"rain_mm_h": RAIN, "gust_kmh": GUST, "feels_like_c": HEAT},
               wettest=notable[:5], hottest=sorted(notable, key=lambda x: -(x["feels_c"] or 0))[:3],
               triggered=[n for n in notable if n["events"]])

    # River floods (GloFAS via Open-Meteo Flood API)
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://flood-api.open-meteo.com/v1/flood", params={
                "latitude": lats, "longitude": lons, "forecast_days": 3,
                "daily": "river_discharge,river_discharge_median"})
            r.raise_for_status()
            fl = r.json()
            fl = fl if isinstance(fl, list) else [fl]
        for p, d in zip(points, fl):
            daily = d.get("daily", {})
            q, med = daily.get("river_discharge") or [], daily.get("river_discharge_median") or []
            ratios = [a / b for a, b in zip(q, med) if a is not None and b]
            if not ratios:
                continue
            ratio = max(ratios)
            ev = river_event(p, ratio, max(x for x in q if x is not None), now)
            if ev:
                events.append(ev)
        trace.step("Open-Meteo river discharge (GloFAS)", places=len(fl), thresholds_ratio=RIVER,
                   has_median_field=any((d.get("daily") or {}).get("river_discharge_median") for d in fl))
    except Exception as exc:
        log.warning("open-meteo flood failed: %s", exc)
    return events
