"""Estimated flooding where nobody has sent a photo yet (fills the gaps on the map).

Idea: water collects in LOW GROUND. When it rains hard, the lowest spots of a
neighbourhood flood first. We combine:
  - rain: last 6 h + next 3 h (Open-Meteo)
  - terrain: 7x7 grid of elevations every 300 m around each watched place
    (Open-Meteo Elevation API, Copernicus 90 m DEM — coarse, so it's a hint, not a measure)
For each grid cell: sink_m = mean(8 neighbours) - own elevation  (how much lower it sits)
  est_depth_cm = min(100, (rain_mm - DRAIN_MM) * 1.2 * (1 + sink_m / 3))
  emitted only if sink_m >= 1.0 and est_depth_cm >= 8
Output: flood events with data.kind="estimated", confidence 0.25-0.4, drawn as flat,
faint water on the map and labelled "estimated". Any real report within 600 m wins:
estimates are skipped there.
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta

import httpx

from app import store, trace
from app.geo import haversine_m
from app.models import HazardEvent, utcnow

log = logging.getLogger("flood_model")
DRAIN_MM = 12          # what poor urban drainage absorbs before pooling starts
RAIN_TRIGGER_MM = 15   # only model places with at least this much rain (6 h past + 3 h ahead)
GRID, STEP_M = 7, 300


async def _rain(points: list[dict]) -> list[float]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": ",".join(str(p["lat"]) for p in points),
            "longitude": ",".join(str(p["lon"]) for p in points),
            "hourly": "precipitation", "past_hours": 6, "forecast_hours": 3, "timezone": "UTC"})
        r.raise_for_status()
        d = r.json()
        d = d if isinstance(d, list) else [d]
    return [float(sum(x or 0 for x in dd["hourly"]["precipitation"])) for dd in d]


async def _elevations(coords: list[tuple[float, float]]) -> list[float]:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://api.open-meteo.com/v1/elevation", params={
            "latitude": ",".join(f"{a:.5f}" for a, _ in coords),
            "longitude": ",".join(f"{b:.5f}" for _, b in coords)})
        r.raise_for_status()
        return r.json()["elevation"]


def estimate_cells(center_lat: float, center_lon: float, elev: list[float], rain_mm: float) -> list[dict]:
    """Pure function (unit-testable): grid elevations -> estimated pooling cells."""
    dlat = STEP_M / 111320
    dlon = STEP_M / (111320 * math.cos(math.radians(center_lat)))
    half = GRID // 2
    cells = []
    for i in range(1, GRID - 1):
        for j in range(1, GRID - 1):
            e = elev[i * GRID + j]
            neigh = [elev[(i + a) * GRID + (j + b)] for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]
            sink = sum(neigh) / 8 - e
            depth = min(100.0, max(0.0, (rain_mm - DRAIN_MM) * 1.2 * (1 + max(sink, 0) / 3)))
            if sink >= 1.0 and depth >= 8:
                cells.append({"lat": center_lat + (i - half) * dlat, "lon": center_lon + (j - half) * dlon,
                              "sink_m": round(sink, 1), "depth_cm": round(depth)})
    return cells


def grid_coords(lat: float, lon: float) -> list[tuple[float, float]]:
    dlat = STEP_M / 111320
    dlon = STEP_M / (111320 * math.cos(math.radians(lat)))
    half = GRID // 2
    return [(lat + (i - half) * dlat, lon + (j - half) * dlon) for i in range(GRID) for j in range(GRID)]


def events_for_point(p: dict, rain: float, elev: list[float], observed: list[HazardEvent],
                     now=None, simulated: bool = False) -> list[HazardEvent]:
    """Pure: one watched place + its rain + its 7x7 elevation grid -> estimated flood events."""
    now = now or utcnow()
    out = []
    cells = estimate_cells(p["lat"], p["lon"], elev, rain)
    trace.step(f"{p['name']}: {rain:.0f} mm of rain -> {len(cells)} low-ground cell(s)",
               formula="depth_cm = min(100, (rain_mm - 12) * 1.2 * (1 + sink_m / 3)); needs sink >= 1 m and depth >= 8 cm",
               cells=cells, elevation_min=min(elev), elevation_max=max(elev))
    for c in cells:
        if any(haversine_m(c["lat"], c["lon"], o.lat, o.lon) < 600 for o in observed):
            trace.step("skip estimate: a real report exists within 600 m", cell=c)
            continue
        sev = "danger" if (c["depth_cm"] >= 40 and rain >= 40) else "warning" if c["depth_cm"] >= 15 else "info"
        out.append(HazardEvent(
            id=f"{'sim-' if simulated else ''}est-{c['lat']:.4f}-{c['lon']:.4f}", type="flood", severity=sev,
            title=f"Possible flooding in low ground (est. ~{c['depth_cm']} cm)",
            description=f"Estimated from {rain:.0f} mm of rain and terrain (this spot sits "
                        f"{c['sink_m']} m below its surroundings). No photo yet — send one if you're there.",
            lat=c["lat"], lon=c["lon"], radius_m=200,
            confidence=round(min(0.4, 0.2 + rain / 200 + c["sink_m"] / 20), 2),
            source="model", observed_at=now, expires_at=now + timedelta(hours=2), is_simulated=simulated,
            data={"kind": "estimated", "depth_cm": c["depth_cm"],
                  "level": "ankle" if c["depth_cm"] < 15 else "shin" if c["depth_cm"] < 30 else "knee_car",
                  "rain_mm": round(rain, 1), "sink_m": c["sink_m"]}))
    return out


async def collect(points: list[dict]) -> list[HazardEvent]:
    if not points:
        return []
    try:
        rains = await _rain(points)
    except Exception as exc:
        log.warning("rain fetch failed: %s", exc)
        trace.step("rain fetch failed", error=str(exc)[:200])
        return []
    wet = [(p, r) for p, r in zip(points, rains) if r >= RAIN_TRIGGER_MM]
    trace.step(f"Rain (6 h past + 3 h ahead) at {len(rains)} places; {len(wet)} over {RAIN_TRIGGER_MM} mm",
               wettest=sorted([{"place": p["name"], "rain_mm": round(r, 1)} for p, r in zip(points, rains)],
                              key=lambda x: -x["rain_mm"])[:5])
    observed = [e for e in store.active(["flood"]) if e.data.get("kind") == "observed"]
    out = []
    for p, rain in wet:
        try:
            elev = await _elevations(grid_coords(p["lat"], p["lon"]))
        except Exception as exc:
            log.warning("elevation fetch failed: %s", exc)
            continue
        out += events_for_point(p, rain, elev, observed)
    return out
