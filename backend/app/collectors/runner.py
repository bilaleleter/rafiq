"""Runs every collector on a schedule and records each source's health.
Each collector owns its "source" name; replace_source() swaps in its fresh picture.
Every run is recorded as a "collector" trace (see app/trace.py)."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from app import config, store, trace
from app.collectors import fires_quakes, flood_model, news_agent, weather, web_photos

log = logging.getLogger("runner")

WATCH_POINTS: dict[str, dict] = {}     # id -> {id, name, lat, lon}; destinations + trip endpoints
SOURCE_HEALTH: dict[str, dict] = {}    # source -> {ok, events, last_run, error}
LAST_RUN: dict = {"at": None, "seconds": None, "running": False}


def load_seed_points():
    for d in json.loads((config.DATA_DIR / "destinations_seed.json").read_text(encoding="utf-8")):
        WATCH_POINTS[d["id"]] = {k: d[k] for k in ("id", "name", "lat", "lon")}


def watch(point_id: str, name: str, lat: float, lon: float):
    """Called when a tourist picks a destination/route so we watch the weather there too."""
    WATCH_POINTS[point_id] = {"id": point_id, "name": name, "lat": round(lat, 3), "lon": round(lon, 3)}


def _summary(events) -> list[str]:
    return [f"{e.severity} {e.type}: {e.title} ({e.confidence:.0%})" for e in events[:12]]


async def _run(source: str, coro_fn, title: str):
    t = time.time()
    with trace.span("collector", title, source=source) as sp:
        try:
            events = await coro_fn()
            store.replace_source(source, events)
            SOURCE_HEALTH[source] = {"ok": True, "events": len(events), "last_run": time.time(),
                                     "seconds": round(time.time() - t, 1)}
            sp.set(events=len(events), published=_summary(events))
        except Exception as exc:  # a collector must never kill the loop
            log.exception("collector %s failed", source)
            SOURCE_HEALTH[source] = {"ok": False, "error": str(exc)[:200], "last_run": time.time()}
            sp.fail(str(exc)[:200])


async def run_once():
    LAST_RUN["running"] = True
    t0 = time.time()
    pts = list(WATCH_POINTS.values())[:90]  # Open-Meteo multi-location limit safety
    with trace.span("collector", f"Weather + rivers for {len(pts)} watched places", source="open-meteo") as sp:
        try:
            wx = await weather.collect(pts)
            store.replace_source("open-meteo", [e for e in wx if e.source == "open-meteo"])
            store.replace_source("open-meteo-flood", [e for e in wx if e.source == "open-meteo-flood"])
            SOURCE_HEALTH["open-meteo"] = {"ok": True, "events": len(wx), "last_run": time.time()}
            sp.set(events=len(wx), published=_summary(wx))
        except Exception as exc:
            SOURCE_HEALTH["open-meteo"] = {"ok": False, "error": str(exc)[:200], "last_run": time.time()}
            sp.fail(str(exc)[:200])
    await asyncio.gather(
        _run("firms", fires_quakes.fires, "NASA FIRMS satellite fires"),
        _run("usgs", fires_quakes.quakes, "USGS earthquakes"),
        _run("news", news_agent.collect, "News agent (Google News FR/AR -> AI -> map)"),
        _run("model", lambda: flood_model.collect(pts[:30]), "Terrain flood model (rain + low ground)"),
    )
    with trace.span("collector", "Web flood-photo agent (YouTube/Flickr)", source="web-photos") as sp:
        try:
            n = await web_photos.collect(pts)
            SOURCE_HEALTH["web-photos"] = {"ok": True, "accepted": n, "last_run": time.time()}
            sp.set(accepted=n)
        except Exception as exc:
            SOURCE_HEALTH["web-photos"] = {"ok": False, "error": str(exc)[:200], "last_run": time.time()}
            sp.fail(str(exc)[:200])
    LAST_RUN.update(at=time.time(), seconds=round(time.time() - t0, 1), running=False)


async def loop():
    load_seed_points()
    while True:
        try:
            await run_once()
        except Exception:
            log.exception("collector round failed")
            LAST_RUN["running"] = False
        await asyncio.sleep(config.COLLECT_EVERY_MIN * 60)
