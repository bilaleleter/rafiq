"""Simulation lab (testing tool): make things "happen" in Tunisia on demand.

Every simulated input goes through the SAME code as real data (threshold grading,
crowd merging, flood fusion, the news agent's AI extraction, the terrain model, the
vision model), so testing here tests the real pipelines. Everything produced is
is_simulated=True, shows a SIMULATED tag, is never removed by real collectors and is
wiped by POST /api/sim/reset.

POST /api/sim/hazard        one event of any type/severity/confidence, anywhere
POST /api/sim/crowd         N fake phones report the same thing (watch confidence rise)
POST /api/sim/weather       made-up readings (rain, gusts, heat, river) -> real thresholds
POST /api/sim/rain-model    made-up rain + REAL terrain -> terrain flood model
POST /api/sim/news          made-up headlines -> real news agent (AI extraction + geocoding)
POST /api/sim/flood-photo   any photo, any place -> real vision pipeline (EXIF check skipped)
POST /api/sim/on-route      drop a hazard on the route you are driving (tests the route guardian)
POST /api/sim/scenario      ready-made mixes ("around_me", "country", "flood_here", ...)
POST /api/sim/reset         remove every simulated thing
GET  /api/sim/presets       sample headlines + scenario list for the app
"""
from __future__ import annotations

import asyncio
import math
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app import config, llm, store, trace
from app.collectors import flood_model, news_agent, weather
from app.geo import haversine_m
from app.models import HazardEvent, utcnow
from app.reports import flood, generic, power
from app.security import require_admin


def require_dev(_: None = Depends(require_admin)) -> None:
    """Traces and system state: testing only."""
    if not config.DEV_MODE:
        raise HTTPException(404, "testing tools are off (DEV_MODE=0)")


def require_sim(request: Request, _: None = Depends(require_admin)) -> None:
    """Simulation lab: on in testing (DEV_MODE) and in public demos (DEMO_MODE)."""
    if not (config.DEV_MODE or config.DEMO_MODE):
        raise HTTPException(404, "simulation is off (DEV_MODE=0 and DEMO_MODE=0)")
    creating = request.method == "POST" and not request.url.path.endswith("/reset")
    if creating and sum(e.is_simulated for e in store.active()) >= config.MAX_SIMULATED:
        raise HTTPException(429, "Too many simulated items right now. Clear them first.")


router = APIRouter(prefix="/api/sim", tags=["simulation"], dependencies=[Depends(require_sim)])
TYPES = ["flood", "fire", "power", "water", "storm", "wind", "heat", "earthquake", "accident", "road", "health",
         "crowd", "other"]
TITLES = {"flood": "Flooded street", "fire": "Active fire", "power": "Power cut", "water": "Water cut",
          "storm": "Heavy rain", "wind": "Strong wind gusts", "heat": "Extreme heat", "earthquake": "Earthquake",
          "accident": "Road accident", "road": "Road blocked", "health": "Health emergency",
          "crowd": "Very crowded area", "other": "Problem reported"}
SAMPLE_HEADLINES = [
    "Nabeul : la route GP1 coupée près de Bir Bouregba après des pluies torrentielles",
    "Coupure d'eau potable dans plusieurs quartiers de Sfax ce mardi, annonce la SONEDE",
    "Incendie de forêt à Aïn Draham : la protection civile mobilisée",
    "Accident de la route sur l'autoroute A1 près d'Enfidha : circulation perturbée",
    "انقطاع التيار الكهربائي في عدة أحياء بسوسة بسبب عطب فني",
    "فيضانات في ولاية نابل وغلق الطريق بين قرمبالية وسليمان",
    "L'Espérance de Tunis remporte le derby face au Club Africain",   # should be ignored (sport)
    "Il y a 20 ans, les inondations de Tunis de 2003",                 # should be ignored (past event)
]


def _offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    return lat + north_m / 111320, lon + east_m / (111320 * math.cos(math.radians(lat)))


# ── one hazard ──────────────────────────────────────────────────────────────
class HazardSpec(BaseModel):
    type: str = "accident"
    severity: str = "danger"
    lat: float
    lon: float
    radius_m: float = 400
    confidence: float = Field(0.8, ge=0, le=1)
    title: str | None = None
    description: str | None = None
    minutes: float = 180
    source: str = "demo"
    data: dict = Field(default_factory=dict)


def make(spec: HazardSpec) -> HazardEvent:
    if spec.type not in TYPES:
        raise HTTPException(400, f"type must be one of {TYPES}")
    now = utcnow()
    return store.upsert(HazardEvent(
        id=f"sim-{uuid.uuid4().hex[:8]}", type=spec.type, severity=spec.severity,
        title=spec.title or TITLES[spec.type], lat=spec.lat, lon=spec.lon, radius_m=spec.radius_m,
        description=spec.description or "Simulated for testing.", confidence=spec.confidence,
        source=spec.source, is_simulated=True, observed_at=now, expires_at=now + timedelta(minutes=spec.minutes),
        data=spec.data))


@router.post("/hazard")
def sim_hazard(spec: HazardSpec):
    with trace.span("sim", f"Simulated {spec.severity} {spec.type}", confidence=spec.confidence) as t:
        e = make(spec)
        st = store.status_of([e])
        t.step(f"Status rule -> {st}", rule="avoid needs danger/critical AND confidence >= 0.5")
        return {"event": e, "status_rule": st}


# ── crowd: N fake phones ────────────────────────────────────────────────────
class CrowdSim(BaseModel):
    type: str = "accident"
    lat: float
    lon: float
    devices: int = Field(3, ge=1, le=12)
    spread_m: float = 120
    note: str = ""
    body_level: str = "person_knee"        # flood only
    charger_verified: bool = False         # power only
    interval_s: float = Field(0, ge=0, le=120)   # >0: reports arrive one by one (watch it live)


async def _crowd(c: CrowdSim, run: str) -> list[dict]:
    steps = []
    with trace.span("sim", f"{c.devices} simulated phones report {c.type}", interval_s=c.interval_s) as t:
        for i in range(c.devices):
            if i and c.interval_s:
                await asyncio.sleep(c.interval_s)
            ang = 2 * math.pi * i / max(1, c.devices)
            lat, lon = _offset(c.lat, c.lon, math.sin(ang) * c.spread_m * (i > 0), math.cos(ang) * c.spread_m * (i > 0))
            dev = f"sim-{run}-{i}"
            try:
                if c.type == "flood":
                    out = await flood._report(lat, lon, c.body_level, c.note, dev, 15, None, simulated=True)
                    e = out.get("zone")
                elif c.type == "power":
                    out = power.ingest(power.PowerReport(lat=lat, lon=lon, device_id=dev, accuracy_m=15,
                                                         charger_verified=c.charger_verified), simulated=True)
                    e = out.get("event")
                else:
                    e = generic.ingest(generic.CrowdReport(type=c.type, lat=lat, lon=lon, note=c.note,
                                                           device_id=dev, accuracy_m=15), simulated=True)
            except HTTPException as exc:
                t.step(f"phone {i + 1}: rejected ({exc.detail})")
                continue
            if e is not None:
                e = e if isinstance(e, HazardEvent) else HazardEvent(**e)
                snap = {"phone": i + 1, "event_id": e.id, "confidence": e.confidence, "severity": e.severity,
                        "status": store.status_of([e]), "reports": e.reports_count}
                steps.append(snap)
                t.step(f"after phone {i + 1}: {e.severity}, {e.confidence:.0%} -> {snap['status']}")
    return steps


@router.post("/crowd")
async def sim_crowd(c: CrowdSim):
    if c.type not in TYPES:
        raise HTTPException(400, f"type must be one of {TYPES}")
    run = uuid.uuid4().hex[:6]
    if c.interval_s:
        asyncio.create_task(_crowd(c, run))
        return {"started": True, "devices": c.devices, "every_s": c.interval_s}
    return {"progression": await _crowd(c, run)}


# ── weather readings through the real thresholds ────────────────────────────
class WeatherSim(BaseModel):
    lat: float
    lon: float
    name: str = "Test place"
    rain_mm_h: float = 0
    gust_kmh: float = 0
    feels_like_c: float = 0
    river_ratio: float = 0


@router.post("/weather")
def sim_weather(w: WeatherSim):
    p = {"id": f"{w.lat:.3f}-{w.lon:.3f}", "name": w.name, "lat": w.lat, "lon": w.lon}
    with trace.span("sim", f"Simulated weather at {w.name}", readings=w.model_dump(),
                    thresholds={"rain_mm_h": weather.RAIN, "gust_kmh": weather.GUST, "feels_like_c": weather.HEAT,
                                "river_ratio": weather.RIVER}) as t:
        evs = weather.events_from_readings(p, w.rain_mm_h or None, w.gust_kmh or None, w.feels_like_c or None,
                                           simulated=True)
        if w.river_ratio:
            rv = weather.river_event(p, w.river_ratio, 50, simulated=True)
            evs += [rv] if rv else []
        for e in evs:
            store.upsert(e)
        t.step(f"{len(evs)} event(s) crossed a threshold", events=[f"{e.severity} {e.type}: {e.title}" for e in evs])
        if not evs:
            t.step("Nothing crossed a threshold: no event (this is the expected behaviour)")
    return {"events": evs}


# ── terrain flood model with made-up rain ───────────────────────────────────
class RainModelSim(BaseModel):
    lat: float
    lon: float
    rain_mm: float = 60
    name: str = "Test place"
    terrain: str = "real"    # "real" (Open-Meteo elevation) | "bowl" (synthetic dip, offline)


def _bowl() -> list[float]:
    g, half = flood_model.GRID, flood_model.GRID // 2
    return [20 + 0.9 * math.hypot(i - half, j - half) ** 1.6 + (3 if (i, j) == (half - 1, half + 1) else 0)
            for i in range(g) for j in range(g)]


@router.post("/rain-model")
async def sim_rain_model(r: RainModelSim):
    with trace.span("sim", f"Terrain flood model: {r.rain_mm:.0f} mm at {r.name}", terrain=r.terrain) as t:
        elev = None
        if r.terrain == "real":
            try:
                elev = await flood_model._elevations(flood_model.grid_coords(r.lat, r.lon))
                t.step("Real elevation grid (7x7, 300 m) from Open-Meteo", elevations=elev)
            except Exception as exc:
                t.step("Elevation API failed: using a synthetic bowl", error=str(exc)[:120])
        if elev is None:
            elev = _bowl()
        observed = [e for e in store.active(["flood"]) if e.data.get("kind") == "observed"]
        p = {"id": "sim", "name": r.name, "lat": r.lat, "lon": r.lon}
        evs = flood_model.events_for_point(p, r.rain_mm, elev, observed, simulated=True)
        for e in evs:
            store.upsert(e)
        if not evs:
            t.step("No low ground deep enough here: try more rain, another place, or terrain='bowl'")
    return {"events": evs, "elevations": elev}


# ── news agent with made-up headlines ───────────────────────────────────────
class NewsSim(BaseModel):
    headlines: list[str] = Field(default_factory=lambda: SAMPLE_HEADLINES[:4])


@router.post("/news")
async def sim_news(n: NewsSim):
    if not llm.available():
        raise HTTPException(503, "the news agent needs the AI key (LLM_API_KEY)")
    with trace.span("sim", f"News agent on {len(n.headlines)} test headline(s)") as t:
        heads = [{"title": h, "link": None} for h in n.headlines if h.strip()][:20]
        evs = await news_agent.extract_events(heads, simulated=True)
        for e in evs:
            store.upsert(e)
        t.set(events=len(evs))
    return {"events": evs}


# ── any photo through the vision pipeline ───────────────────────────────────
@router.post("/flood-photo")
async def sim_flood_photo(lat: float = Form(...), lon: float = Form(...), photo: UploadFile = File(...)):
    with trace.span("sim", "Flood photo through the vision pipeline (EXIF check skipped)") as t:
        out = await flood._report(lat, lon, None, "", f"sim-photo-{uuid.uuid4().hex[:6]}", 15, photo,
                                  simulated=True, skip_exif=True)
        t.set(accepted=out.get("accepted"), reason=out.get("reason"),
              depth_cm=out.get("depth_cm"), anchor=(out.get("analysis") or {}).get("anchor"))
        return out


# ── drop a hazard on the route being driven ─────────────────────────────────
class OnRouteSim(BaseModel):
    coordinates: list[list[float]]
    type: str = "accident"
    severity: str = "danger"
    confidence: float = 0.8
    at_fraction: float = Field(0.5, ge=0, le=1)


@router.post("/on-route")
def sim_on_route(o: OnRouteSim):
    if len(o.coordinates) < 2:
        raise HTTPException(400, "need a route")
    cum = [0.0]
    for a, b in zip(o.coordinates, o.coordinates[1:]):
        cum.append(cum[-1] + haversine_m(a[0], a[1], b[0], b[1]))
    goal = cum[-1] * o.at_fraction
    i = next((k for k, c in enumerate(cum) if c >= goal), len(cum) - 1)
    lat, lon = o.coordinates[i]
    with trace.span("sim", f"Hazard dropped on the route at {goal / 1000:.1f} km") as t:
        e = make(HazardSpec(type=o.type, severity=o.severity, lat=lat, lon=lon, radius_m=250,
                            confidence=o.confidence, description="Simulated on your route to test the route guardian."))
        t.step("The route guardian re-checks on every live update and every 30 s: an alert should appear")
    return {"event": e, "km": round(goal / 1000, 1)}


# ── scenarios ───────────────────────────────────────────────────────────────
COUNTRY = [
    dict(type="storm", severity="danger", title="Heavy rain: up to 22 mm/h", lat=36.40, lon=10.60,
         radius_m=9000, confidence=0.8, description="Simulated storm cell over Hammamet."),
    dict(type="fire", severity="critical", title="Active forest fire", lat=36.80, lon=8.70,
         radius_m=2500, confidence=0.85, description="Simulated fire near Aïn Draham."),
    dict(type="power", severity="warning", title="Power cut reported (4 people)", lat=35.826, lon=10.637,
         radius_m=1500, confidence=0.7, description="Simulated outage in Sousse medina."),
    dict(type="road", severity="danger", title="Road blocked (3 people)", lat=36.55, lon=10.45,
         radius_m=400, confidence=0.8, description="Simulated closure on the Tunis–Hammamet road."),
    dict(type="heat", severity="warning", title="Extreme heat: 40 °C feels-like", lat=33.92, lon=8.13,
         radius_m=15000, confidence=0.75, description="Simulated heat in Tozeur."),
]


class ScenarioReq(BaseModel):
    name: str = "around_me"
    lat: float | None = None
    lon: float | None = None
    speed: float = 60


def country_demo() -> int:
    now = utcnow()
    for i, d in enumerate(COUNTRY):
        store.upsert(HazardEvent(id=f"demo-{i}", source="demo", is_simulated=True,
                                 observed_at=now, expires_at=now + timedelta(hours=3), **d))
    return len(COUNTRY)


@router.post("/scenario")
async def sim_scenario(s: ScenarioReq):
    lat, lon = (s.lat, s.lon) if s.lat is not None and s.lon is not None else tuple(config.PROFILE["center"])
    with trace.span("sim", f"Scenario: {s.name}", lat=round(lat, 4), lon=round(lon, 4)) as t:
        if s.name == "country":
            n = country_demo()
            t.step(f"{n} simulated incidents across Tunisia")
            return {"created": n}
        if s.name == "flood_here":
            items = flood.load_replay(center=(lat, lon))
            flood.start_replay(items, s.speed)
            t.step(f"Flood replay moved to your position: {len(items)} reports over ~2 h, played x{s.speed}")
            return {"started": True, "reports": len(items)}
        if s.name == "flood_hammamet":
            items = flood.load_replay()
            flood.start_replay(items, s.speed)
            return {"started": True, "reports": len(items)}
        if s.name == "around_me":
            made = []
            # a road blocked by 3 phones (-> avoid), an accident seen by 1 phone (-> caution only)
            made += await _crowd(CrowdSim(type="road", lat=_offset(lat, lon, 0, 2500)[0],
                                          lon=_offset(lat, lon, 0, 2500)[1], devices=3, note="Police blocking the road"),
                                 uuid.uuid4().hex[:6])
            made += await _crowd(CrowdSim(type="accident", lat=_offset(lat, lon, -1800, 0)[0],
                                          lon=_offset(lat, lon, -1800, 0)[1], devices=1), uuid.uuid4().hex[:6])
            made += await _crowd(CrowdSim(type="power", lat=_offset(lat, lon, 0, -900)[0],
                                          lon=_offset(lat, lon, 0, -900)[1], devices=2, charger_verified=True),
                                 uuid.uuid4().hex[:6])
            made += await _crowd(CrowdSim(type="flood", lat=_offset(lat, lon, 1300, 900)[0],
                                          lon=_offset(lat, lon, 1300, 900)[1], devices=3, body_level="person_mid_calf"),
                                 uuid.uuid4().hex[:6])
            p = {"id": "around", "name": "your area", "lat": _offset(lat, lon, -6000, 4000)[0],
                 "lon": _offset(lat, lon, -6000, 4000)[1]}
            for e in weather.events_from_readings(p, rain=18, gust=None, feels=None, simulated=True):
                store.upsert(e)
            make(HazardSpec(type="water", severity="warning", confidence=0.4, source="news", radius_m=1500,
                            title="Water cut announced (news, unverified)",
                            lat=_offset(lat, lon, 3500, -2500)[0], lon=_offset(lat, lon, 3500, -2500)[1]))
            t.step("Created: road blocked (3 phones), accident (1 phone), power cut (2 phones, charger-verified), "
                   "flood (3 body reports), heavy rain (18 mm/h -> danger), water cut (news 40%)")
            return {"created": len(made) + 2, "progression": made}
        raise HTTPException(400, "unknown scenario")


@router.post("/reset")
def sim_reset():
    with trace.span("sim", "Reset all simulated data") as t:
        flood.replay_reset()
        cells = power.clear_simulated()
        n = store.clear(simulated_only=True)
        t.set(events_removed=n, power_cells=cells)
    return {"cleared": n}


@router.get("/presets")
def presets():
    return {"headlines": SAMPLE_HEADLINES, "types": TYPES,
            "scenarios": ["around_me", "flood_here", "country", "flood_hammamet"],
            "llm": llm.available()}
