"""Web flood-photo agent: finds flood photos/videos people post online and turns the
ones that pass a strict check into flood reports on the 3D map.

SOURCES (all legal, official APIs):
  - YouTube Data API v3 search (free: 10,000 units/day; one search = 100 units)
  - Flickr photo search (free non-commercial key; photos carry GPS + date taken)
  - Links people share in the app: TikTok and YouTube via their public oEmbed
    endpoints (title + thumbnail). TikTok has NO public search API (its Research
    API is for academics) and scraping breaks its terms — so TikTok enters through
    user-shared links, not crawling.
It only searches while it is actually raining somewhere in the country (saves quota
and avoids recycled footage on dry days).

THE CHECK (every candidate, every step logged in /api/flood/web-log):
  1. FRESH        published/taken < WEB_MAX_AGE_H (default 24 h) ago
  2. NOT RECYCLED perceptual hash of the image vs everything seen before; a match with
                  an older item = re-post of old footage -> rejected
  3. REAL + DEPTH vision model: real photo of flood water? not AI-generated / not a
                  graphic? where is the waterline (anchor -> cm, same as in-app photos)
  4. WHERE        GPS (Flickr) > pin dropped by the sharer > LLM place extraction from
                  title/description + geocoding; must be inside the country and at least
                  neighbourhood-precise
  5. RAINED THERE Open-Meteo: ≥ 3 mm of rain at that spot in the last ~24 h, otherwise it
                  cannot be today's flood -> rejected
Survivors enter the flood fusion as method "web", confidence capped at 0.5, with the
thumbnail + link kept as public evidence (it is already public content).
"""
from __future__ import annotations

import io
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import httpx

from app import config, llm, trace
from app.collectors.news_agent import stable_id
from app.reports import flood
from app.services.google import geocode

log = logging.getLogger("web_photos")
WEB_LOG: deque = deque(maxlen=100)       # transparency: every decision + reasons
_seen_hashes: dict[int, datetime] = {}   # perceptual hash -> earliest publish time
_done_ids: set[str] = set()
_last_search = 0.0
SEARCH_EVERY_S = 30 * 60

WEB_PROMPT = f"""You check a photo/video thumbnail posted online during a storm.
Answer ONLY this JSON:
{{"is_flood_scene": true|false, "real_photo": true|false,
 "looks_ai_generated_or_edited": true|false, "is_graphic_or_text_card": true|false,
 "anchor": "<one of: {', '.join(flood.ANCHORS_CM)} or null>",
 "flowing_water": true|false, "visible_dangers": ["..."],
 "place_clues": "<shop signs, landmarks, writing visible, or empty>",
 "confidence": 0.0-1.0}}
anchor = where the WATERLINE sits on the clearest reference object."""

GEO_PROMPT = """Extract where this flood footage was filmed. Input: title, description,
visual clues. Reply JSON: {"place": "<most specific place, e.g. 'Avenue Habib Bourguiba,
Nabeul'>", "specificity": "street|neighbourhood|city|region|unknown", "confidence": 0-1}.
Never guess: if the text doesn't say, use "unknown"."""


# ── helpers ─────────────────────────────────────────────────────────────────
def _log(item: dict, ok: bool, reason: str, **extra):
    trace.event("agent", f"Web photo {'ACCEPTED' if ok else 'rejected'}: {reason}", ok=ok,
                platform=item.get("platform"), url=item.get("url"), title=item.get("title"), **extra)
    WEB_LOG.appendleft({"at": datetime.now(timezone.utc).isoformat(), "accepted": ok, "reason": reason,
                        "platform": item.get("platform"), "url": item.get("url"),
                        "title": (item.get("title") or "")[:120], **extra})
    return {"accepted": ok, "reason": reason, **extra}


def _ahash(raw: bytes) -> int | None:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("L").resize((8, 8))
        px = list(img.get_flattened_data()) if hasattr(img, "get_flattened_data") else list(img.getdata())
        avg = sum(px) / 64
        return sum(1 << i for i, p in enumerate(px) if p > avg)
    except Exception:
        return None


def _recycled(h: int, published: datetime) -> bool:
    for old_h, first in _seen_hashes.items():
        if bin(old_h ^ h).count("1") <= 5 and published - first > timedelta(hours=config.WEB_MAX_AGE_H):
            return True
    _seen_hashes.setdefault(h, published)
    return False


def _in_country(lat, lon) -> bool:
    w, s, e, n = config.PROFILE["bbox"]
    return w <= lon <= e and s <= lat <= n


async def rain_mm_last_day(lat: float, lon: float) -> float | None:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lon, "hourly": "precipitation",
                "past_hours": 30, "forecast_hours": 1, "timezone": "UTC"})
            r.raise_for_status()
            return float(sum(x or 0 for x in r.json()["hourly"]["precipitation"]))
    except Exception as exc:
        log.warning("rain check failed: %s", exc)
        return None


# ── sources ─────────────────────────────────────────────────────────────────
async def search_youtube(query: str, lang: str, since: datetime) -> list[dict]:
    if not config.YOUTUBE_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://www.googleapis.com/youtube/v3/search", params={
                "part": "snippet", "q": query, "type": "video", "order": "date", "maxResults": 15,
                "publishedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"), "regionCode": config.COUNTRY,
                "relevanceLanguage": lang, "key": config.YOUTUBE_API_KEY})
            r.raise_for_status()
        out = []
        for it in r.json().get("items", []):
            sn = it["snippet"]
            vid = it["id"]["videoId"]
            out.append({"id": f"yt-{vid}", "platform": "youtube", "url": f"https://www.youtube.com/watch?v={vid}",
                        "title": sn.get("title"), "description": sn.get("description", ""),
                        "published": datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")),
                        "thumb": (sn.get("thumbnails", {}).get("high") or sn.get("thumbnails", {}).get("default", {})).get("url")})
        return out
    except Exception as exc:
        log.warning("youtube search failed: %s", exc)
        return []


async def search_flickr(text: str, since: datetime) -> list[dict]:
    if not config.FLICKR_API_KEY:
        return []
    w, s, e, n = config.PROFILE["bbox"]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://www.flickr.com/services/rest/", params={
                "method": "flickr.photos.search", "api_key": config.FLICKR_API_KEY, "text": text,
                "bbox": f"{w},{s},{e},{n}", "min_taken_date": int(since.timestamp()), "has_geo": 1,
                "extras": "geo,date_taken,date_upload,url_m,description", "per_page": 30,
                "format": "json", "nojsoncallback": 1})
            r.raise_for_status()
        out = []
        for p in r.json().get("photos", {}).get("photo", []):
            if not p.get("url_m"):
                continue
            out.append({"id": f"fl-{p['id']}", "platform": "flickr",
                        "url": f"https://www.flickr.com/photos/{p['owner']}/{p['id']}",
                        "title": p.get("title"), "description": (p.get("description") or {}).get("_content", ""),
                        "published": datetime.fromtimestamp(int(p["dateupload"]), timezone.utc),
                        "thumb": p["url_m"], "lat": float(p["latitude"]), "lon": float(p["longitude"]),
                        "geo_source": "gps"})
        return out
    except Exception as exc:
        log.warning("flickr search failed: %s", exc)
        return []


async def from_link(url: str) -> dict | None:
    """User-shared TikTok / YouTube link -> candidate via public oEmbed."""
    endpoints = {"tiktok.com": "https://www.tiktok.com/oembed",
                 "youtube.com": "https://www.youtube.com/oembed", "youtu.be": "https://www.youtube.com/oembed"}
    ep = next((v for k, v in endpoints.items() if k in url), None)
    if not ep:
        return None
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(ep, params={"url": url, "format": "json"})
            r.raise_for_status()
            j = r.json()
        return {"id": stable_id("link", url), "platform": "tiktok" if "tiktok" in url else "youtube",
                "url": url, "title": j.get("title", ""), "description": j.get("author_name", ""),
                "published": None, "thumb": j.get("thumbnail_url")}
    except Exception as exc:
        log.warning("oembed failed for %s: %s", url, exc)
        return None


# ── the check ───────────────────────────────────────────────────────────────
async def verify_and_add(item: dict, pin: tuple[float, float] | None = None,
                         shared_now: bool = False) -> dict:
    if item["id"] in _done_ids:
        return {"accepted": False, "reason": "already processed"}
    _done_ids.add(item["id"])
    now = datetime.now(timezone.utc)

    published = item.get("published") or (now if shared_now else None)
    if not published or now - published > timedelta(hours=config.WEB_MAX_AGE_H):
        return _log(item, False, "too old (or unknown date)")
    if not item.get("thumb"):
        return _log(item, False, "no image")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            raw = (await c.get(item["thumb"])).content
    except Exception:
        return _log(item, False, "image download failed")

    h = _ahash(raw)
    if h is not None and _recycled(h, published):
        return _log(item, False, "recycled: same image was already online earlier")

    b64 = __import__("base64").b64encode(flood._shrink_jpeg(raw)).decode()
    v = llm.extract_json(await llm.chat([{"role": "user", "content": [
        {"type": "text", "text": WEB_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        model=config.VISION_MODEL, max_tokens=400, temperature=0.1, timeout=45, purpose="web photo agent: check image"))
    if not isinstance(v, dict):
        return _log(item, False, "vision model unavailable")
    if not v.get("is_flood_scene") or not v.get("real_photo"):
        return _log(item, False, "not a real flood photo")
    if v.get("looks_ai_generated_or_edited") or v.get("is_graphic_or_text_card"):
        return _log(item, False, "looks AI-generated, edited or a graphic")
    if v.get("anchor") not in flood.ANCHORS_CM:
        return _log(item, False, "no readable waterline")

    # location
    if item.get("lat") is not None:
        lat, lon, loc_q, place = item["lat"], item["lon"], 1.0, "GPS"
    elif pin:
        lat, lon, loc_q, place = pin[0], pin[1], 0.9, "pinned by sharer"
    else:
        g = await llm.chat_json(GEO_PROMPT, f"Title: {item.get('title')}\nDescription: {item.get('description', '')[:500]}\n"
                                            f"Visual clues: {v.get('place_clues', '')}", purpose="web photo agent: where was it filmed")
        spec = (g or {}).get("specificity", "unknown")
        if not g or spec in ("region", "unknown") or float(g.get("confidence", 0)) < 0.5:
            return _log(item, False, "location too vague")
        loc = await geocode(f"{g['place']}, {config.PROFILE['name']}", config.COUNTRY.lower())
        if not loc:
            return _log(item, False, f"could not locate '{g['place']}'")
        lat, lon, place = loc[0], loc[1], g["place"]
        loc_q = {"street": 0.9, "neighbourhood": 0.75, "city": 0.5}.get(spec, 0.5)
    if not _in_country(lat, lon):
        return _log(item, False, "outside the country")

    rain = await rain_mm_last_day(lat, lon)
    if rain is not None and rain < 3:
        return _log(item, False, f"no rain recorded there in the last day ({rain:.1f} mm) — likely old footage")

    conf = min(0.5, float(v.get("confidence") or 0.5) * 0.6 * loc_q * (1.0 if rain is not None else 0.8))
    ev = flood.add_report(flood.Report(
        lat, lon, flood.ANCHORS_CM[v["anchor"]], conf, min(published, now), "web",
        bool(v.get("flowing_water")), v.get("visible_dangers") or [], item.get("title") or "",
        evidence_url=item["thumb"], source_url=item["url"]), place=place)
    return _log(item, True, "accepted", depth_cm=flood.ANCHORS_CM[v["anchor"]], place=place,
                confidence=round(conf, 2), rain_mm=rain, zone_id=ev.id)


async def raining_somewhere(points: list[dict]) -> bool:
    for p in points[:12]:
        mm = await rain_mm_last_day(p["lat"], p["lon"])
        if mm and mm >= 5:
            return True
    return False


async def collect(points: list[dict]) -> int:
    """Called by the runner. Returns accepted count. Searches at most every 30 min, only when it rains."""
    global _last_search
    if time.time() - _last_search < SEARCH_EVERY_S or not llm.available():
        return 0
    if not (config.YOUTUBE_API_KEY or config.FLICKR_API_KEY):
        return 0
    _last_search = time.time()
    if not await raining_somewhere(points):
        return 0
    since = datetime.now(timezone.utc) - timedelta(hours=config.WEB_MAX_AGE_H)
    items = []
    for lang, q in config.PROFILE.get("flood_queries", []):
        items += await search_youtube(q, lang, since)
    items += await search_flickr("flood OR inondation OR فيضان", since)
    accepted = 0
    for it in items[:40]:
        res = await verify_and_add(it)
        accepted += bool(res.get("accepted"))
    return accepted


# ── API ─────────────────────────────────────────────────────────────────────
from fastapi import APIRouter, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.reports import trust  # noqa: E402

router = APIRouter(prefix="/api/flood", tags=["flood"])


class SharedLink(BaseModel):
    url: str
    lat: float | None = None      # where the sharer says it was filmed (pin on the map)
    lon: float | None = None
    device_id: str = "anon"


@router.post("/link")
async def share_link(s: SharedLink):
    """Someone saw a TikTok/YouTube flood video: paste the link (+ drop a pin)."""
    ok, why = trust.allow(s.device_id, "flood-link")
    if not ok:
        raise HTTPException(429, why)
    trust.record(s.device_id, "flood-link")
    item = await from_link(s.url)
    if not item:
        raise HTTPException(400, "Only TikTok and YouTube links are supported for now.")
    pin = (s.lat, s.lon) if s.lat is not None and s.lon is not None else None
    # oEmbed gives no upload date: accepted only if shared now AND it rained there recently
    return await verify_and_add(item, pin=pin, shared_now=True)


@router.get("/web-log")
def web_log():
    """Every web candidate and why it was accepted or rejected (transparency)."""
    return list(WEB_LOG)
