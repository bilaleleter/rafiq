"""News agent — the "agentic retrieval" for problems no API publishes
(water cuts, power cuts, closed roads, local floods, accidents, strikes).

Pipeline:
  1. Google News RSS search in French + Arabic (last 24 h)      -> headlines + links
  2. LLM extracts structured incidents (JSON, strict schema)    -> type, place, severity
  3. Geocode the place name                                     -> lat/lon
  4. HazardEvent with LOW confidence (0.3-0.5) + the article link as source
News can only ever produce "caution" on its own (see store.status_of): it needs
corroboration from a crowd report or a sensor feed to cause "avoid".
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import timedelta

import httpx

from app import config, llm, trace
from app.models import HazardEvent, utcnow
from app.services.google import geocode

log = logging.getLogger("news")
TYPES = {"flood", "fire", "power", "water", "storm", "wind", "heat", "earthquake", "accident", "road", "health", "crowd", "other"}

SYSTEM = """You extract CURRENT public-safety incidents from news headlines for travellers.
Input: numbered headlines (French or Arabic). Output JSON:
{"incidents": [{"i": <headline number>, "type": "flood|fire|power|water|road|accident|storm|health|crowd|other",
  "place": "<most specific place name + governorate, in Latin letters>",
  "severity": "warning|danger|critical", "happening_now": true|false,
  "summary_en": "<max 12 words>", "confidence": 0.0-1.0}]}
Rules: only incidents happening now or in the next 48 h; skip politics, sports, opinion,
anniversaries and past events; power/water cuts are "warning" unless hospitals or a whole
city are affected; if unsure, skip it."""


async def _headlines() -> list[dict]:
    items = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        for lang, q in config.PROFILE["news_queries"]:
            try:
                r = await c.get("https://news.google.com/rss/search",
                                params={"q": q, "hl": lang, "gl": config.COUNTRY,
                                        "ceid": f"{config.COUNTRY}:{lang}"})
                for it in ET.fromstring(r.text).iter("item"):
                    items.append({"title": it.findtext("title"), "link": it.findtext("link")})
            except Exception as exc:
                log.warning("news RSS failed (%s): %s", lang, exc)
    seen, uniq = set(), []
    for it in items:
        key = (it["title"] or "")[:60]
        if key and key not in seen:
            seen.add(key)
            uniq.append(it)
    return uniq[:40]


def clean_place(place: str) -> str:
    """'A1 highway near Enfidha' -> 'Enfidha'. Road codes (A1, GP1, RN8, C50) and words like
    'highway' or 'near' make geocoders land on the wrong end of a 600 km road."""
    parts = []
    for part in str(place).split(","):
        p = re.sub(r"\b[A-Z]{1,3}\s?\d{1,3}\b", " ", part)
        p = re.sub(r"(?i)\b(highway|motorway|autoroute|route|road|near|close to|près de|entre|between|and|et)\b", " ", p)
        p = re.sub(r"\s+", " ", p).strip(" -")
        if p:
            parts.append(p)
    return ", ".join(parts) or str(place)


def in_country(lat: float, lon: float) -> bool:
    w, s, e, n = config.PROFILE["bbox"]
    return w <= lon <= e and s <= lat <= n


def stable_id(prefix: str, key: str) -> str:
    """Same input -> same id across restarts (Python's hash() is salted per process)."""
    return f"{prefix}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


async def extract_events(heads: list[dict], simulated: bool = False) -> list[HazardEvent]:
    """headlines [{title, link}] -> AI extraction -> geocode -> low-confidence events.
    Shared by the live collector and the simulation lab (which feeds made-up headlines)."""
    if not heads:
        return []
    trace.step(f"{len(heads)} headlines to read", headlines=[h["title"] for h in heads])
    listing = "\n".join(f"{i}. {h['title']}" for i, h in enumerate(heads))
    out = await llm.chat_json(SYSTEM, listing, purpose="news agent: extract incidents")
    incidents = (out or {}).get("incidents", []) if isinstance(out, dict) else []
    trace.step(f"AI extracted {len(incidents)} incident(s)", incidents=incidents)
    now, events = utcnow(), []
    for inc in incidents:
        try:
            if not inc.get("happening_now"):
                trace.step(f"skip #{inc.get('i')}: not happening now")
                continue
            h = heads[int(inc["i"])]
            loc = await geocode(f"{clean_place(inc['place'])}, {config.PROFILE['name']}", config.COUNTRY.lower())
            if loc and not in_country(*loc):
                trace.step(f"'{inc['place']}' geocoded outside the country: ignored", lat=loc[0], lon=loc[1])
                loc = None
            if not loc:
                trace.step(f"skip #{inc.get('i')}: could not place '{inc.get('place')}' on the map")
                continue
            typ = inc.get("type") if inc.get("type") in TYPES else "other"
            sev = inc.get("severity") if inc.get("severity") in ("warning", "danger", "critical") else "warning"
            conf = min(0.5, float(inc.get("confidence", 0.4)))
            events.append(HazardEvent(
                id=stable_id("sim-news" if simulated else "news", h.get("link") or h["title"]), type=typ,
                severity=sev, title=inc.get("summary_en") or h["title"][:80],
                description=f"From the news: “{h['title']}” (auto-extracted, unverified)",
                lat=loc[0], lon=loc[1], radius_m=3000, confidence=conf,
                source="news", source_url=h.get("link"), observed_at=now, is_simulated=simulated,
                expires_at=now + timedelta(hours=12), data={"place": inc.get("place")}))
            trace.step(f"placed #{inc['i']}: {typ}/{sev} at {inc.get('place')}", lat=loc[0], lon=loc[1],
                       confidence=conf, note="capped at 50%: news alone can only ever cause 'caution'")
        except Exception as exc:
            trace.step(f"skip incident: {exc}", incident=inc)
            log.debug("skipping incident %s: %s", inc, exc)
    return events


async def collect() -> list[HazardEvent]:
    if not llm.available():
        return []
    return await extract_events(await _headlines())
