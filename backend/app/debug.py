"""Under-the-hood endpoints for the testing panel (hidden when DEV_MODE=0).

GET  /api/debug/traces?kind&limit   recent traces (newest first)
GET  /api/debug/stream              SSE: every new trace, live
POST /api/debug/clear               empty the trace buffer
GET  /api/debug/state               snapshot: events per source, collectors, AI models, Google usage,
                                    translation/voice providers, flood zones, power cells, trust state
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import Counter

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app import config, llm, store, trace
from app.collectors import runner
from app.reports import flood, power, trust
from app.services import google, language
from app.sim import require_dev

router = APIRouter(prefix="/api/debug", tags=["debug"], dependencies=[Depends(require_dev)])


@router.get("/traces")
def traces(kind: str | None = None, limit: int = 200):
    return trace.recent(kind, limit)


@router.post("/clear")
def clear():
    trace.clear()
    return {"cleared": True}


@router.get("/stream")
async def stream(request: Request):
    q = trace.subscribe()

    async def gen():
        try:
            yield f"data: {json.dumps({'kind': 'hello', 'recent': trace.recent(limit=80)}, default=str)}\n\n"
            while not await request.is_disconnected():
                try:
                    rec = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps({'kind': 'trace', 'trace': rec}, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            trace.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/state")
async def state():
    evs = store.active()
    now = time.time()
    return {
        "events": {"total": len(evs), "simulated": sum(e.is_simulated for e in evs),
                   "by_source": Counter(e.source for e in evs), "by_type": Counter(e.type for e in evs),
                   "by_status": Counter(store.status_of([e]) for e in evs)},
        "collectors": {"health": runner.SOURCE_HEALTH, "last_round": runner.LAST_RUN,
                       "watch_points": len(runner.WATCH_POINTS), "every_min": config.COLLECT_EVERY_MIN},
        "ai": {"key": llm.available(), "text_model": config.LLM_MODEL, "vision_model": config.VISION_MODEL,
               "fallbacks": {"text": config.LLM_FALLBACK_MODELS, "vision": config.VISION_FALLBACK_MODELS},
               "last_ok": llm.LAST_OK,
               "cooling_down": {m: round(t - now) for m, t in llm._down_until.items() if t > now}},
        "google": {"server_key": google.has_key(), "browser_key": bool(config.GOOGLE_BROWSER_KEY),
                   "usage": google.STATS, "cached_queries": len(google._cache), "cached_photos": len(google._photos)},
        "language": await language.status(),
        "flood_zones": [{"id": z.id, "reports": len(z.reports), "simulated": z.simulated, "place": z.place}
                        for z in flood._zones.values()],
        "power_cells": [{"cell": k, "devices_off": len(c["off"]), "devices_on": len(c["on"]), "sim": c.get("sim")}
                        for k, c in power._cells.items()],
        "trust": {"devices_seen": len(trust._recent),
                  "reputation": {d[:10]: r for d, r in list(trust._reputation.items())[:20]}},
        "traces_buffered": len(trace.TRACES),
    }
