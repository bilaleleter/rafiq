"""API entry point.  Run:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import config, debug, llm, sim, store, trace
from app.collectors import runner, web_photos
from app.models import HazardEvent
from app.reports import flood, generic, power
from app.security import require_admin
from app.services import briefing, destinations, google, language, places, sos, trip

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# httpx logs every request URL at INFO; some Google endpoints carry ?key=..., so keep keys out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if os.getenv("COLLECTORS", "on") != "off":
        task = asyncio.create_task(runner.loop())
        # warm the place cache (Google photos/ratings for the curated places) so the first visitor waits less
        asyncio.create_task(_warm())
    else:
        runner.load_seed_points()
    yield
    if task:
        task.cancel()


async def _warm():
    try:
        c = config.PROFILE["center"]
        await destinations.candidates(c[0], c[1], 150)
    except Exception:
        logging.getLogger("warm").warning("cache warm-up failed", exc_info=True)


app = FastAPI(title="Rafiq — travel safety API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (flood.router, web_photos.router, generic.router, power.router, sos.router, destinations.router, trip.router,
          briefing.router, places.router, language.router, sim.router, debug.router):
    app.include_router(r)


# ── Hazards (the shared contract) ───────────────────────────────────────────
@app.get("/api/hazards", response_model=list[HazardEvent], tags=["hazards"])
def list_hazards(type: list[str] | None = Query(None)):
    return store.active(type)


@app.post("/api/hazards", response_model=HazardEvent, tags=["hazards"], dependencies=[Depends(require_admin)])
def create_hazard(e: HazardEvent):
    return store.upsert(e)


@app.delete("/api/hazards/{event_id}", tags=["hazards"], dependencies=[Depends(require_admin)])
def delete_hazard(event_id: str):
    if not store.remove(event_id):
        raise HTTPException(404, "unknown event")
    return {"deleted": event_id}


class Vote(BaseModel):
    still_there: bool


@app.post("/api/hazards/{event_id}/vote", tags=["hazards"])
def vote(event_id: str, v: Vote):
    e = store.vote(event_id, v.still_there)
    if not e:
        raise HTTPException(404, "unknown event")
    return e


@app.get("/api/hazards/near", tags=["hazards"])
def near(lat: float, lon: float, radius_km: float = 3):
    hits = store.near(lat, lon, radius_km * 1000)
    return {"status": store.status_of([h["event"] for h in hits]), "hits": hits}


@app.get("/api/stream", tags=["hazards"])
async def stream(request: Request):
    """Server-Sent Events: {kind: "snapshot"|"upsert"|"remove", ...}. The app keeps one open."""
    q = store.subscribe()

    async def gen():
        try:
            snap = [e.model_dump(mode="json") for e in store.active()]
            yield f"data: {json.dumps({'kind': 'snapshot', 'events': snap})}\n\n"
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(msg, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            store.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── System ──────────────────────────────────────────────────────────────────
@app.get("/api/public-config", tags=["system"])
async def public_config():
    lang = await language.status()
    return {"google_maps_key": config.GOOGLE_BROWSER_KEY, "google_map_id": config.GOOGLE_MAP_ID,
            "country": config.COUNTRY, "center": config.PROFILE["center"],
            "emergency_numbers": config.PROFILE["emergency_numbers"],
            "dev_mode": config.DEV_MODE, "demo_mode": config.DEMO_MODE, "admin_required": bool(config.ADMIN_TOKEN),
            "features": {"places": google.has_key(), "ai": llm.available(),
                         "translate": lang["translate"], "tts": lang["tts"]}}


@app.get("/api/health", tags=["system"])
def health():
    return {"ok": True, "events": len(store.active()), "llm": llm.available(),
            "llm_models": {"text": config.LLM_MODEL, "vision": config.VISION_MODEL, "last_ok": llm.LAST_OK},
            "google": google.has_key(), "firms": bool(config.FIRMS_MAP_KEY),
            "sources": runner.SOURCE_HEALTH, "last_round": runner.LAST_RUN}


@app.post("/api/collect-now", tags=["system"], dependencies=[Depends(require_admin)])
async def collect_now():
    await runner.run_once()
    return {"sources": runner.SOURCE_HEALTH}


# ── Demo scenario (always labelled is_simulated). Kept for older clients; see app/sim.py ──
@app.post("/api/demo/scenario", tags=["demo"], dependencies=[Depends(require_admin)])
def demo_scenario():
    n = sim.country_demo()
    trace.event("sim", f"Demo scenario: {n} simulated incidents")
    return {"created": n}


@app.post("/api/demo/reset", tags=["demo"], dependencies=[Depends(require_admin)])
def demo_reset():
    return sim.sim_reset()


# ── Built frontend (Docker single-container option): served at / when backend/static exists ──
_STATIC = config.BASE_DIR / "static"
if _STATIC.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="web")
