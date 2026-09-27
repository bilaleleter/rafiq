"""Google Maps Platform (server side) with free fallbacks.

Places (New) nearby / text search / autocomplete / details / photos
                              -> no fallback (recommendations use the seed list)
Routes computeRoutes         -> fallback: OSRM public demo server
Geocoding (forward/reverse)  -> fallback: OpenStreetMap Nominatim (1 req/s max!)

Place results are cached 30 min per (area, types) and photos are proxied + cached,
so the server key never reaches the browser and repeated screens cost nothing.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

import httpx

from app import config, trace
from app.geo import decode_polyline, haversine_m

log = logging.getLogger("google")
UA = {"User-Agent": "rafiq-hackathon/0.1"}
PLACES = "https://places.googleapis.com/v1"
PLACE_FIELDS = ("id,displayName,location,rating,userRatingCount,primaryType,types,formattedAddress,"
                "shortFormattedAddress,nationalPhoneNumber,currentOpeningHours.openNow,photos,priceLevel,"
                "editorialSummary,googleMapsUri")
DETAIL_FIELDS = PLACE_FIELDS + ",regularOpeningHours.weekdayDescriptions,websiteUri,internationalPhoneNumber"
CACHE_TTL_S = 30 * 60
_cache: dict[str, tuple[float, object]] = {}
_photos: OrderedDict[str, tuple[float, str]] = OrderedDict()   # key -> (time, CDN url)
STATS = {"places_calls": 0, "cache_hits": 0, "photo_calls": 0, "photo_cache_hits": 0}


def has_key() -> bool:
    return bool(config.GOOGLE_SERVER_KEY)


def _cached(key: str):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        STATS["cache_hits"] += 1
        return hit[1]
    return None


def _store(key: str, value):
    _cache[key] = (time.time(), value)
    if len(_cache) > 600:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)
    return value


# ── Places ──────────────────────────────────────────────────────────────────
async def places_nearby(lat: float, lon: float, radius_m: float, types: list[str],
                        max_results: int = 20, rank_by_distance: bool = False,
                        language: str = "en") -> list[dict]:
    if not has_key():
        return []
    key = f"nb:{lat:.2f}:{lon:.2f}:{int(radius_m)}:{','.join(types)}:{max_results}:{rank_by_distance}:{language}"
    if (hit := _cached(key)) is not None:
        return hit
    body = {"includedTypes": types, "maxResultCount": max_results, "languageCode": language,
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                               "radius": min(radius_m, 50_000)}}}
    if rank_by_distance:
        body["rankPreference"] = "DISTANCE"
    try:
        STATS["places_calls"] += 1
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{PLACES}/places:searchNearby", json=body,
                             headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY,
                                      "X-Goog-FieldMask": ",".join(f"places.{f}" for f in PLACE_FIELDS.split(","))})
            r.raise_for_status()
            out = r.json().get("places", [])
            trace.step(f"Google Places nearby: {','.join(types)[:60]}", results=len(out), radius_km=round(radius_m / 1000))
            return _store(key, out)
    except Exception as exc:
        log.warning("places_nearby failed: %s", exc)
        trace.step(f"Google Places nearby FAILED ({','.join(types)[:40]})", error=str(exc)[:200])
        return []


async def places_text(query: str, lat: float | None = None, lon: float | None = None,
                      max_results: int = 20, language: str = "en") -> list[dict]:
    if not has_key() or not query.strip():
        return []
    key = f"tx:{query.lower()}:{lat and round(lat, 1)}:{lon and round(lon, 1)}:{max_results}:{language}"
    if (hit := _cached(key)) is not None:
        return hit
    body = {"textQuery": query, "maxResultCount": max_results, "languageCode": language}
    if lat is not None and lon is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": 50_000}}
    try:
        STATS["places_calls"] += 1
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{PLACES}/places:searchText", json=body,
                             headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY,
                                      "X-Goog-FieldMask": ",".join(f"places.{f}" for f in PLACE_FIELDS.split(","))})
            r.raise_for_status()
            out = r.json().get("places", [])
            trace.step(f"Google Places text search '{query[:40]}'", results=len(out))
            return _store(key, out)
    except Exception as exc:
        log.warning("places_text failed: %s", exc)
        return []


async def autocomplete(text: str, lat: float | None, lon: float | None, session: str | None = None,
                       language: str = "en") -> list[dict]:
    """-> [{place_id, main, secondary, types, distance_m}] (Google Maps-style search box)."""
    if not has_key() or not text.strip():
        return []
    body = {"input": text, "languageCode": language}
    if lat is not None and lon is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": 50_000}}
        body["origin"] = {"latitude": lat, "longitude": lon}
    if session:
        body["sessionToken"] = session
    try:
        STATS["places_calls"] += 1
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{PLACES}/places:autocomplete", json=body,
                             headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY})
            r.raise_for_status()
        out = []
        for s in r.json().get("suggestions", []):
            p = s.get("placePrediction")
            if not p:
                continue
            fmt = p.get("structuredFormat", {})
            out.append({"place_id": p.get("placeId"),
                        "main": (fmt.get("mainText") or {}).get("text") or (p.get("text") or {}).get("text"),
                        "secondary": (fmt.get("secondaryText") or {}).get("text", ""),
                        "types": p.get("types", []), "distance_m": p.get("distanceMeters")})
        return out
    except Exception as exc:
        log.warning("autocomplete failed: %s", exc)
        return []


async def place_details(place_id: str, language: str = "en", session: str | None = None) -> dict | None:
    if not has_key():
        return None
    key = f"dt:{place_id}:{language}"
    if (hit := _cached(key)) is not None:
        return hit
    params = {"languageCode": language}
    if session:
        params["sessionToken"] = session
    try:
        STATS["places_calls"] += 1
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{PLACES}/places/{place_id}", params=params,
                            headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY, "X-Goog-FieldMask": DETAIL_FIELDS})
            r.raise_for_status()
            return _store(key, r.json())
    except Exception as exc:
        log.warning("place_details failed: %s", exc)
        return None


async def place_photo_url(name: str, max_px: int = 480) -> str | None:
    """Public Google CDN URL for a Places photo (no key in it). The browser then loads the image
    straight from Google's CDN, which is much faster than streaming it through our server.
    Cached for 50 min (Google's photo URLs are short-lived)."""
    if not has_key() or not name.startswith("places/") or "/photos/" not in name:
        return None
    max_px = max(64, min(1600, max_px))
    key = f"{name}@{max_px}"
    hit = _photos.get(key)
    if hit and time.time() - hit[0] < 50 * 60:
        STATS["photo_cache_hits"] += 1
        return hit[1]
    try:
        STATS["photo_calls"] += 1
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{PLACES}/{name}/media",
                            params={"maxWidthPx": max_px, "skipHttpRedirect": "true", "key": config.GOOGLE_SERVER_KEY})
            r.raise_for_status()
        uri = r.json().get("photoUri")
        if uri:
            _photos[key] = (time.time(), uri)
            while len(_photos) > 2000:
                _photos.popitem(last=False)
        return uri
    except Exception as exc:
        log.warning("place_photo failed: %s", exc)
        return None


def first_photo(p: dict) -> str | None:
    ph = p.get("photos") or []
    return ph[0].get("name") if ph else None


# ── Routes ──────────────────────────────────────────────────────────────────
async def routes(o_lat, o_lon, d_lat, d_lon, mode: str = "DRIVE",
                 via: tuple[float, float] | None = None) -> list[dict]:
    """-> [{coords: [[lat,lon]...], duration_s, distance_m, label, provider}] (1-3 alternatives).
    via = one waypoint to force a detour (then Google returns a single route)."""
    if has_key():
        body = {"origin": {"location": {"latLng": {"latitude": o_lat, "longitude": o_lon}}},
                "destination": {"location": {"latLng": {"latitude": d_lat, "longitude": d_lon}}},
                "travelMode": mode, "computeAlternativeRoutes": via is None}
        if via:
            body["intermediates"] = [{"via": True, "location": {"latLng": {"latitude": via[0], "longitude": via[1]}}}]
        if mode == "DRIVE":
            body["routingPreference"] = "TRAFFIC_AWARE"
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post("https://routes.googleapis.com/directions/v2:computeRoutes", json=body,
                                 headers={"X-Goog-Api-Key": config.GOOGLE_SERVER_KEY,
                                          "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,"
                                                              "routes.polyline.encodedPolyline,routes.description"})
                r.raise_for_status()
                out = []
                for i, rt in enumerate(r.json().get("routes", [])):
                    out.append({"coords": decode_polyline(rt["polyline"]["encodedPolyline"]),
                                "duration_s": int(str(rt.get("duration", "0s")).rstrip("s") or 0),
                                "distance_m": rt.get("distanceMeters", 0),
                                "label": rt.get("description") or f"Route {i + 1}",
                                "provider": "google"})
                if out:
                    trace.step("Google Routes", mode=mode, alternatives=len(out))
                    return out
        except Exception as exc:
            log.warning("Google routes failed, falling back to OSRM: %s", exc)
            trace.step("Google Routes failed, trying OSRM", error=str(exc)[:200])
    return await _osrm(o_lat, o_lon, d_lat, d_lon, mode, via)


async def _osrm(o_lat, o_lon, d_lat, d_lon, mode, via=None) -> list[dict]:
    profile = {"WALK": "foot", "BICYCLE": "bike"}.get(mode, "driving")
    mid = f";{via[1]},{via[0]}" if via else ""
    url = (f"https://router.project-osrm.org/route/v1/{profile}/{o_lon},{o_lat}{mid};{d_lon},{d_lat}"
           f"?alternatives={'false' if via else 'true'}&overview=full&geometries=geojson")
    try:
        async with httpx.AsyncClient(timeout=15, headers=UA) as c:
            r = await c.get(url)
            r.raise_for_status()
            out = [{"coords": [[p[1], p[0]] for p in rt["geometry"]["coordinates"]],
                    "duration_s": int(rt["duration"]), "distance_m": int(rt["distance"]),
                    "label": f"Route {i + 1}", "provider": "osrm"}
                   for i, rt in enumerate(r.json().get("routes", []))]
            trace.step("OSRM routes (fallback)", alternatives=len(out),
                       note="public OSRM only has car routes" if mode == "WALK" else None)
            return out
    except Exception as exc:
        log.warning("OSRM failed: %s", exc)
        return []


# ── Geocoding ───────────────────────────────────────────────────────────────
async def geocode(text: str, region: str = "tn") -> tuple[float, float] | None:
    try:
        async with httpx.AsyncClient(timeout=10, headers=UA) as c:
            if has_key():
                r = await c.get("https://maps.googleapis.com/maps/api/geocode/json",
                                params={"address": text, "region": region, "key": config.GOOGLE_SERVER_KEY})
                res = r.json().get("results", [])
                if res:
                    loc = res[0]["geometry"]["location"]
                    trace.step(f"Geocoded '{text[:60]}' (Google)", lat=loc["lat"], lon=loc["lng"])
                    return loc["lat"], loc["lng"]
            r = await c.get("https://nominatim.openstreetmap.org/search",
                            params={"q": text, "format": "json", "limit": 1, "countrycodes": region})
            res = r.json()
            if res:
                trace.step(f"Geocoded '{text[:60]}' (Nominatim)", lat=res[0]["lat"], lon=res[0]["lon"])
                return float(res[0]["lat"]), float(res[0]["lon"])
    except Exception as exc:
        log.warning("geocode failed for %r: %s", text, exc)
    trace.step(f"Could not geocode '{text[:60]}'")
    return None


async def reverse_geocode(lat: float, lon: float, language: str = "fr") -> dict:
    """-> {address, plus_code}. Plus codes work even where streets have no address."""
    out = {"address": None, "plus_code": None}
    try:
        async with httpx.AsyncClient(timeout=10, headers=UA) as c:
            if has_key():
                r = await c.get("https://maps.googleapis.com/maps/api/geocode/json",
                                params={"latlng": f"{lat},{lon}", "language": language,
                                        "key": config.GOOGLE_SERVER_KEY})
                j = r.json()
                if j.get("results"):
                    out["address"] = j["results"][0]["formatted_address"]
                out["plus_code"] = (j.get("plus_code") or {}).get("global_code")
                if out["address"]:
                    return out
            r = await c.get("https://nominatim.openstreetmap.org/reverse",
                            params={"lat": lat, "lon": lon, "format": "json", "accept-language": language})
            out["address"] = r.json().get("display_name")
    except Exception as exc:
        log.warning("reverse geocode failed: %s", exc)
    return out


def distance_m(lat, lon, p: dict) -> float:
    loc = p.get("location", {})
    return haversine_m(lat, lon, loc.get("latitude", lat), loc.get("longitude", lon))
