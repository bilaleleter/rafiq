"""Google Maps-style place search for the app (server-proxied: the key never reaches the browser).

GET /api/places/autocomplete?input&lat&lon&session   -> suggestions while typing
GET /api/places/details?id&lat&lon                    -> one place + its live status (clear/caution/avoid)
GET /api/places/search?q&lat&lon                      -> full text search ("pharmacy", "couscous Sousse"...)
GET /api/places/photo?name&w                          -> redirect to the Google CDN image (cached URL)
GET /api/places/nearby?lat&lon&kind                   -> hospitals/pharmacies/police/fuel... by distance
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app import trace
from app.services import google
from app.services.destinations import assess, from_place

router = APIRouter(prefix="/api/places", tags=["places"])
NEARBY_KINDS = {"hospital": ["hospital"], "pharmacy": ["pharmacy"], "police": ["police"],
                "fuel": ["gas_station"], "atm": ["atm"], "hotel": ["hotel", "lodging"]}


def _with_status(d, lat, lon) -> dict:
    out = {**d.model_dump(), **assess(d)}
    if lat is not None and lon is not None:
        out["distance_km"] = round(google.haversine_m(lat, lon, d.lat, d.lon) / 1000, 1)
    return out


@router.get("/autocomplete")
async def autocomplete(input: str, lat: float | None = None, lon: float | None = None,
                       session: str | None = None, lang: str = "en"):
    return {"suggestions": await google.autocomplete(input, lat, lon, session, lang), "google": google.has_key()}


@router.get("/details")
async def details(id: str, lat: float | None = None, lon: float | None = None,
                  session: str | None = None, lang: str = "en"):
    with trace.span("api", "Place details", id=id) as t:
        p = await google.place_details(id, lang, session)
        if not p:
            t.fail("not found or Google unavailable")
            raise HTTPException(404, "place not found")
        d = from_place(p)
        if not d:
            raise HTTPException(404, "place has no location")
        out = _with_status(d, lat, lon)
        out.update({"phone": p.get("internationalPhoneNumber") or p.get("nationalPhoneNumber"),
                    "website": p.get("websiteUri"), "maps_url": p.get("googleMapsUri"),
                    "hours": (p.get("regularOpeningHours") or {}).get("weekdayDescriptions"),
                    "photos": [ph.get("name") for ph in (p.get("photos") or [])[:6]]})
        t.set(name=d.name, category=d.category, status=out["status"])
        return out


@router.get("/search")
async def search(q: str, lat: float | None = None, lon: float | None = None, lang: str = "en"):
    with trace.span("api", f"Place search: {q[:40]}") as t:
        places = await google.places_text(q, lat, lon, 20, lang)
        out = [_with_status(d, lat, lon) for d in (from_place(p) for p in places) if d]
        t.set(results=len(out))
        return {"results": out, "google": google.has_key()}


@router.get("/photo")
async def photo(name: str, w: int = 480):
    """Redirects to Google's image CDN (fast, no key in the URL)."""
    url = await google.place_photo_url(name, w)
    if not url:
        raise HTTPException(404, "photo unavailable")
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "public, max-age=1800"})


@router.get("/nearby")
async def nearby(lat: float, lon: float, kind: str = "hospital", lang: str = "en"):
    types = NEARBY_KINDS.get(kind)
    if not types:
        raise HTTPException(400, f"kind must be one of {list(NEARBY_KINDS)}")
    places = await google.places_nearby(lat, lon, 15_000, types, 10, rank_by_distance=True, language=lang)
    return {"results": [{**_with_status(d, lat, lon), "phone": p.get("nationalPhoneNumber")}
                        for p in places if (d := from_place(p, kind))]}
