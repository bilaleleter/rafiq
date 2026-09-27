"""AI briefing: turns the raw hazard list for a place/route into 2-4 plain sentences
in the tourist's language, each with an ACTION. Grounded: the model only sees
our events (with sources); it may not add facts. Deterministic fallback if the LLM fails
(translated when the tourist's language isn't English)."""
from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app import llm, store, trace

router = APIRouter(prefix="/api/briefing", tags=["briefing"])
LANG_NAME = {"en": "English", "fr": "French", "ar": "Arabic", "de": "German", "it": "Italian", "es": "Spanish"}
LANG_CODE = {v: k for k, v in LANG_NAME.items()}

SYSTEM = """You are a calm, practical travel-safety assistant for tourists.
You receive a place and a list of CURRENT reported issues (with source, confidence, age).
Write 2-4 short sentences in {lang}. Rules:
- Use ONLY the issues given. Never invent facts, numbers or places.
- Mention uncertainty for low-confidence items ("unconfirmed report").
- Every issue gets a concrete action (avoid X, go earlier, carry water, choose route B...).
- If there are no issues: say there are no reported issues right now (NEVER say "safe").
Return JSON: {{"headline": "<max 8 words>", "text": "<the sentences>"}}"""


class BriefingRequest(BaseModel):
    lat: float
    lon: float
    name: str = "your destination"
    lang: str = "English"          # a language name ("Arabic") or code ("ar")
    radius_m: float = 5000


def _fallback(name: str, hits: list[dict]) -> dict:
    if not hits:
        return {"headline": "No reported issues right now",
                "text": f"No problems are currently reported around {name}. Conditions can change. "
                        f"You will get an alert if something new appears.", "ai": False}
    lines = [f"{h['event'].title} ({h['distance_m'] / 1000:.1f} km away, "
             f"{'unconfirmed' if h['event'].confidence < 0.5 else 'confirmed'})" for h in hits[:3]]
    return {"headline": f"{len(hits)} issue(s) near {name}", "text": "; ".join(lines) + ".", "ai": False}


async def _localise(out: dict, code: str) -> dict:
    if code == "en":
        return out
    from app.services.language import translate
    texts, provider = await translate([out["headline"], out["text"]], code)
    return {**out, "headline": texts[0], "text": texts[1], "translated_by": provider}


_cache: dict[str, tuple[float, dict]] = {}
CACHE_S = 15 * 60


@router.post("")
async def briefing(req: BriefingRequest):
    """Same place + same live problems + same language -> cached answer (instant, no AI call)."""
    code = LANG_CODE.get(req.lang, req.lang if req.lang in LANG_NAME else "en")
    hits = store.near(req.lat, req.lon, req.radius_m)
    key = f"{req.lat:.3f}|{req.lon:.3f}|{code}|{req.name}|" + ",".join(
        sorted(f"{h['event'].id}:{h['event'].severity}:{h['event'].confidence:.2f}" for h in hits[:8]))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    out = await _briefing(req, code)
    _cache[key] = (time.time(), out)
    if len(_cache) > 500:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)
    return out


async def _briefing(req: BriefingRequest, code: str):
    lang = LANG_NAME[code]
    with trace.span("agent", f"Briefing for {req.name} ({lang})", radius_m=req.radius_m,
                    rule="the model only sees the listed events; no events -> fixed text, no AI call") as t:
        hits = store.near(req.lat, req.lon, req.radius_m)
        if not hits:
            t.step("No events within radius: template text, no AI call")
            return await _localise(_fallback(req.name, hits), code)
        facts = "\n".join(
            f"- {h['event'].type}/{h['event'].severity}: {h['event'].title}. {h['event'].description} "
            f"[{h['distance_m']} m away, confidence {h['event'].confidence:.0%}, source {h['event'].source}]"
            for h in hits[:8])
        t.step("Facts given to the model (nothing else)", facts=facts)
        out = await llm.chat_json(SYSTEM.format(lang=lang), f"Place: {req.name}\nIssues:\n{facts}",
                                  purpose=f"briefing: {req.name}")
        if isinstance(out, dict) and out.get("text"):
            if "safe" in out["text"].lower().split() and code == "en":
                t.step("Model used the word 'safe': replaced by the template (responsible-AI rule)")
                return _fallback(req.name, hits)
            t.set(output=out)
            return {**out, "ai": True, "event_ids": [h["event"].id for h in hits[:8]]}
        t.step("AI unavailable or invalid answer: template fallback")
        return await _localise(_fallback(req.name, hits), code)
