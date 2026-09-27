"""Trip planning + Route Guardian.

/api/trip/plan
  1. get 1-3 route alternatives (Google Routes, OSRM fallback)
  2. check each route against live hazards (store.along_route)
  3. rank: cost = duration_min + penalty; caution hit +20 min each, avoid hit +240 min
  4. every route blocked? try a detour: a waypoint beside the first blocking problem (both sides)
  5. still blocked: recommend the LEAST RISKY route (risk = 10 per avoid hazard, 15 if critical,
     1 per caution) and say when its problems are expected to clear; never leave the user stuck
  6. return every route with its hazards + which one we recommend and WHY
  7. also check the destination itself and suggest alternatives if it's not clear

/api/trip/check  (called by the app every ~30 s and on every live hazard update)
  Takes the REMAINING part of the route (from the user's position) and returns
  the hazards ahead. The frontend alerts once per new event id, and again only
  if that event's severity increases.
"""
from __future__ import annotations

import asyncio
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import store, trace
from app.collectors import runner
from app.services import destinations
from app.geo import haversine_m
from app.services.google import routes

router = APIRouter(prefix="/api/trip", tags=["trip"])
PENALTY = {"clear": 0, "caution": 20, "avoid": 240}


class PlanRequest(BaseModel):
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    dest_name: str = "destination"
    dest_category: str = "sight"
    mode: str = "DRIVE"            # DRIVE | WALK | BICYCLE | TWO_WHEELER


class CheckRequest(BaseModel):
    coordinates: list[list[float]]  # remaining route [[lat, lon], ...]
    buffer_m: float = 250


def _route_penalty(check: dict) -> float:
    p = 0.0
    for h in check["hits"]:
        e = h["event"]
        p += PENALTY["avoid"] if (e.severity in ("danger", "critical") and e.confidence >= 0.5) else \
            PENALTY["caution"] if e.severity != "info" else 0
    return p


def _is_avoid(e) -> bool:
    return e.severity in ("danger", "critical") and e.confidence >= 0.5


def risk_score(route: dict) -> int:
    """How bad a route is: 10 per avoid hazard (15 if critical), 1 per caution hazard."""
    score = 0
    for h in route["hazards"]:
        e = h["event"]
        score += (15 if e.severity == "critical" else 10) if _is_avoid(e) else 1 if e.severity != "info" else 0
    return score


def detour_points(coords: list[list[float]], e) -> list[tuple[float, float]]:
    """Four waypoints beside a blocking hazard (left/right of the road, near/far) to route around it."""
    i = min(range(len(coords)), key=lambda k: haversine_m(e.lat, e.lon, *coords[k]))
    a, b = coords[max(0, i - 3)], coords[min(len(coords) - 1, i + 3)]
    k = math.cos(math.radians(e.lat))
    dy, dx = b[0] - a[0], (b[1] - a[1]) * k
    n = math.hypot(dx, dy) or 1
    px, py = -dy / n, dx / n                     # unit vector perpendicular to the road
    near, far = max(3500, e.radius_m + 2500), min(20000, max(9000, e.radius_m + 6000))
    return [(e.lat + side * py * off / 111320, e.lon + side * px * off / (111320 * k))
            for off in (near, far) for side in (1, -1)]


def _evaluate(r: dict, index: int) -> dict:
    chk = store.along_route(r["coords"])
    out = {"index": index, **r, "safety": chk["status"], "hazards": chk["hits"],
           "cost_min": round(r["duration_s"] / 60 + _route_penalty(chk), 1)}
    out["risk"] = risk_score(out)
    return out


@router.post("/plan")
async def plan(req: PlanRequest):
    with trace.span("calc", f"Plan trip to {req.dest_name}", mode=req.mode,
                    rule="cost = minutes + 20 per caution hit + 240 per avoid hit (within 250 m of the route)") as t:
        runner.watch(f"dest-{req.dest_lat:.3f}-{req.dest_lon:.3f}", req.dest_name, req.dest_lat, req.dest_lon)
        alts = await routes(req.origin_lat, req.origin_lon, req.dest_lat, req.dest_lon, req.mode)
        if not alts:
            t.fail("no route from Google or OSRM")
            raise HTTPException(502, "No route available (routing providers unreachable)")
        evaluated = [_evaluate(r, i) for i, r in enumerate(alts)]
        for r in evaluated:
            t.step(f"Route {r['index'] + 1} ({r['label']}): {r['duration_s'] / 60:.0f} min, {r['distance_m'] / 1000:.1f} km",
                   provider=r["provider"], safety=r["safety"], cost_min=r["cost_min"], risk=r["risk"],
                   hazards=[f"km {h['km_along_route']}: {h['event'].title} ({h['event'].severity}, "
                            f"{h['event'].confidence:.0%}, {h['distance_to_route_m']} m off route)" for h in r["hazards"]])

        # Every route blocked? Try to drive around the first blocking problem (unless it sits on the destination).
        at_destination = any(_is_avoid(e) and haversine_m(req.dest_lat, req.dest_lon, e.lat, e.lon) <= e.radius_m + 300
                             for e in store.active())
        detour_tried = False
        if all(r["safety"] == "avoid" for r in evaluated) and not at_destination:
            fastest = min(evaluated, key=lambda r: r["duration_s"])
            blocker = next((h["event"] for h in fastest["hazards"] if _is_avoid(h["event"])), None)
            if blocker:
                detour_tried = True
                pts = detour_points(fastest["coords"], blocker)
                found = await asyncio.gather(*[routes(req.origin_lat, req.origin_lon, req.dest_lat, req.dest_lon,
                                                      req.mode, via=p) for p in pts])
                for got in found:
                    for r in got[:1]:
                        ev = _evaluate({**r, "label": f"Detour around {blocker.title[:40]}", "detour": True}, len(evaluated))
                        evaluated.append(ev)
                        t.step(f"Detour via waypoint beside '{blocker.title}': {ev['duration_s'] / 60:.0f} min, {ev['safety']}",
                               risk=ev["risk"])

        best = min(evaluated, key=lambda r: r["cost_min"])
        fastest = min(evaluated, key=lambda r: r["duration_s"])
        least = min(evaluated, key=lambda r: (r["risk"], r["duration_s"]))
        if best["index"] == fastest["index"]:
            why = "Fastest route" + (" with no reported issues" if best["safety"] == "clear" else "")
        elif best.get("detour"):
            extra = round((best["duration_s"] - fastest["duration_s"]) / 60)
            why = f"Detour around the reported problem, +{extra} min"
        else:
            extra = round((best["duration_s"] - fastest["duration_s"]) / 60)
            why = f"Avoids {len(fastest['hazards'])} reported issue(s) on the fastest route, +{extra} min"
        unsafe = all(r["safety"] == "avoid" for r in evaluated)
        clears = [h["event"].expires_at for h in least["hazards"] if _is_avoid(h["event"]) and h["event"].expires_at]
        t.step(f"Recommended route {best['index'] + 1}: {why}" + (f"; all unsafe, least risky = route {least['index'] + 1}"
                                                                     if unsafe else ""))
        dest = await destinations.check(req.dest_lat, req.dest_lon, req.dest_name, req.dest_category)
        return {"routes": evaluated, "recommended_index": least["index"] if unsafe else best["index"], "why": why,
                "all_routes_unsafe": unsafe, "least_risk_index": least["index"], "detour_tried": detour_tried,
                "problem_at_destination": at_destination, "clears_at": max(clears) if clears else None,
                "destination": dest}


@router.post("/check")
def check(req: CheckRequest):
    if len(req.coordinates) < 2:
        raise HTTPException(400, "need at least 2 points")
    res = store.along_route(req.coordinates, req.buffer_m)
    trace.event("calc", f"Route guardian: {len(res['hits'])} issue(s) on the remaining {res['route_km']} km",
                status=res["status"], hits=[f"km {h['km_along_route']}: {h['event'].title}" for h in res["hits"]])
    return res
