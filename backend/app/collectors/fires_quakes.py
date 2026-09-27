"""Satellite fire hotspots (NASA FIRMS) + earthquakes (USGS). Both are real, live feeds."""
from __future__ import annotations

import csv
import io
import logging
from datetime import timedelta

import httpx

from app import config
from app.geo import cluster_points, haversine_m
from app.models import HazardEvent, utcnow

log = logging.getLogger("fires")


async def fires() -> list[HazardEvent]:
    """VIIRS hotspots from the last 24 h, clustered within 2 km -> one event per fire."""
    if not config.FIRMS_MAP_KEY:
        return []
    w, s, e, n = config.PROFILE["bbox"]
    url = (f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{config.FIRMS_MAP_KEY}"
           f"/VIIRS_SNPP_NRT/{w},{s},{e},{n}/1")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(url)
            r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
    except Exception as exc:
        log.warning("FIRMS failed: %s", exc)
        return []
    rows = [x for x in rows if x.get("confidence", "n") != "l"]  # drop low-confidence detections
    pts = [(float(x["latitude"]), float(x["longitude"])) for x in rows]
    now = utcnow()
    out = []
    for idx in cluster_points(pts, 2000):
        la = sum(pts[i][0] for i in idx) / len(idx)
        lo = sum(pts[i][1] for i in idx) / len(idx)
        frp = sum(float(rows[i].get("frp") or 0) for i in idx)  # fire radiative power (MW)
        sev = "critical" if frp > 100 or len(idx) >= 10 else "danger" if frp > 20 or len(idx) >= 3 else "warning"
        spread = max(haversine_m(la, lo, *pts[i]) for i in idx)
        out.append(HazardEvent(
            id=f"fire-{la:.3f}-{lo:.3f}", type="fire", severity=sev,
            title=f"Active fire ({len(idx)} satellite hotspot{'s' if len(idx) > 1 else ''})",
            description="Detected by NASA VIIRS satellite in the last 24 h.",
            lat=la, lon=lo, radius_m=max(1000, spread + 1000), confidence=0.8,
            source="firms", source_url="https://firms.modaps.eosdis.nasa.gov/map/",
            observed_at=now, expires_at=now + timedelta(hours=8),
            data={"hotspots": len(idx), "frp_mw": round(frp, 1)}))
    return out


async def quakes() -> list[HazardEvent]:
    """USGS M4.5+ in the last day within ~300 km of the country."""
    w, s, e, n = config.PROFILE["bbox"]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson")
            r.raise_for_status()
            feats = r.json().get("features", [])
    except Exception as exc:
        log.warning("USGS failed: %s", exc)
        return []
    now, out = utcnow(), []
    for f in feats:
        lo, la = f["geometry"]["coordinates"][:2]
        if not (w - 3 <= lo <= e + 3 and s - 3 <= la <= n + 3):
            continue
        mag = f["properties"]["mag"]
        sev = "critical" if mag >= 6.5 else "danger" if mag >= 5.5 else "warning"
        out.append(HazardEvent(
            id=f"eq-{f['id']}", type="earthquake", severity=sev,
            title=f"Earthquake M{mag:.1f}", description=f["properties"].get("place") or "",
            lat=la, lon=lo, radius_m=30_000 * mag / 4.5, confidence=0.95,
            source="usgs", source_url=f["properties"].get("url"),
            observed_at=now, expires_at=now + timedelta(hours=12), data={"magnitude": mag}))
    return out
