"""Destination Advisor: "where should I go right now?" and "is X OK right now?"

Candidates = curated seed list (enriched with Google photos/ratings) + Google Places
around the user, one query per interest (beaches, history, food, cafes, ...).

score = 100 * (0.30*quality + 0.15*popularity + 0.30*interest + 0.25*proximity)
            * safety * open_factor * weather_fit
  quality     Bayesian rating (pulls few-review places toward 4.3): 3★ -> 0, 5★ -> 1
  popularity  log10(reviews + 1) / 4, capped at 1 (10 000 reviews = 1)
  interest    1 if the category is one of the user's interests, else 0.3 (0.5 when none chosen)
  proximity   exp(-km / scale); scale = 6 km food/cafe/nightlife, 15 km shopping, 40 km otherwise
  safety      clear 1.0 | caution 0.6 | avoid 0 (hidden from recommendations, listed apart)
  open_factor open now 1.0 | closed 0.55 | unknown 0.9
  weather_fit rain/wind/heat reported within 10 km: outdoor places x0.75, indoor x1.05
Then a diversity pass: each further place of an already-picked category is x0.85^n,
so the list mixes beaches, food, history... instead of ten cafés in a row.
Every result carries WHY (reason codes the app translates) + its score breakdown.
"""
from __future__ import annotations

import asyncio
import json
import math

from fastapi import APIRouter

from app import config, store, trace
from app.collectors import runner
from app.geo import haversine_m
from app.models import Destination
from app.services import google

router = APIRouter(prefix="/api/destinations", tags=["destinations"])
SAFETY = {"clear": 1.0, "caution": 0.6, "avoid": 0.0}
CHECK_RADIUS_M = 3000

# interest -> (Google Places types, outdoor?)
CATEGORIES: dict[str, tuple[list[str], bool]] = {
    "beach": (["beach"], True),
    "history": (["historical_landmark", "historical_place", "monument", "cultural_landmark", "castle"], True),
    "medina": ([], True),                      # text search "medina souk" + seed list
    "nature": (["national_park", "park", "hiking_area", "garden", "botanical_garden", "scenic_spot"], True),
    "desert": ([], True),                      # seed list (Douz, Tozeur, Ksar Ghilane...)
    "museum": (["museum", "art_gallery"], False),
    "food": (["restaurant"], False),
    "cafe": (["cafe", "coffee_shop", "tea_house", "ice_cream_shop", "bakery"], False),
    "shopping": (["shopping_mall", "market"], False),
    "family": (["amusement_park", "zoo", "aquarium", "water_park"], True),
    "nightlife": (["bar", "night_club"], False),
    "sight": (["tourist_attraction", "observation_deck", "marina", "plaza"], True),
}
# which category a Google type belongs to (checked on primaryType first, then types)
_TYPE_TO_CAT = {t: cat for cat, (types, _) in CATEGORIES.items() for t in types}
_TYPE_TO_CAT.update({"mosque": "history", "church": "history", "synagogue": "history",
                     "national_park": "nature", "restaurant": "food"})
PROX_SCALE_KM = {"food": 6, "cafe": 6, "nightlife": 6, "shopping": 15}
DEFAULT_INTERESTS = ["sight", "history", "beach", "food", "cafe"]
_seed_enriched: dict[str, dict] = {}


def _seed() -> list[Destination]:
    return [Destination(**d) for d in
            json.loads((config.DATA_DIR / "destinations_seed.json").read_text(encoding="utf-8"))]


def category_of(p: dict) -> str:
    name = ((p.get("displayName") or {}).get("text") or "").lower()
    if any(w in name for w in ("medina", "médina", "souk", "مدينة", "سوق")):
        return "medina"
    for t in [p.get("primaryType"), *p.get("types", [])]:
        if t in _TYPE_TO_CAT:
            return _TYPE_TO_CAT[t]
    return "sight"


def from_place(p: dict, category: str | None = None) -> Destination | None:
    loc = p.get("location") or {}
    if "latitude" not in loc:
        return None
    return Destination(
        id=p["id"], name=(p.get("displayName") or {}).get("text", "?"), lat=loc["latitude"], lon=loc["longitude"],
        category=category or category_of(p), rating=p.get("rating"), rating_count=p.get("userRatingCount"),
        source="google_places", place_id=p["id"], photo=google.first_photo(p),
        address=p.get("shortFormattedAddress") or p.get("formattedAddress"),
        open_now=(p.get("currentOpeningHours") or {}).get("openNow"), primary_type=p.get("primaryType"),
        summary=(p.get("editorialSummary") or {}).get("text"), price_level=p.get("priceLevel"))


async def _enrich_seeds(seeds: list[Destination]) -> None:
    """Seed places get the Google photo/rating of the same place (looked up once per process)."""
    todo = [s for s in seeds if s.id not in _seed_enriched]
    if not todo or not google.has_key():
        return
    results = await asyncio.gather(*[google.places_text(f"{s.name}, {config.PROFILE['name']}", s.lat, s.lon, 1)
                                     for s in todo], return_exceptions=True)
    for s, res in zip(todo, results):
        p = res[0] if isinstance(res, list) and res else None
        if p and google.distance_m(s.lat, s.lon, p) < 15_000:
            _seed_enriched[s.id] = {"place_id": p["id"], "photo": google.first_photo(p), "rating": p.get("rating"),
                                    "rating_count": p.get("userRatingCount"),
                                    "address": p.get("shortFormattedAddress") or p.get("formattedAddress"),
                                    "summary": (p.get("editorialSummary") or {}).get("text")}
        else:
            _seed_enriched[s.id] = {}
    trace.step("Seed places matched to Google (photos, ratings)", matched=sum(1 for s in todo if _seed_enriched.get(s.id)),
               of=len(todo))


async def candidates(lat: float, lon: float, max_km: float, interests: list[str] | None = None,
                     language: str = "en") -> list[Destination]:
    ints = [i for i in (interests or []) if i in CATEGORIES] or DEFAULT_INTERESTS
    seeds = [d for d in _seed() if haversine_m(lat, lon, d.lat, d.lon) <= max_km * 1000]
    jobs, labels = [], []
    radius = min(max_km, 50) * 1000
    for cat in dict.fromkeys(["sight", *ints]):
        types = CATEGORIES[cat][0]
        if types:
            r = min(radius, PROX_SCALE_KM.get(cat, 50) * 2000)
            jobs.append(google.places_nearby(lat, lon, r, types, 20, language=language))
            labels.append(cat)
        elif cat == "medina":
            jobs.append(google.places_text("medina souk", lat, lon, 10, language))
            labels.append(cat)
    results = await asyncio.gather(*jobs, _enrich_seeds(seeds))
    out: dict[str, Destination] = {}
    for d in seeds:
        e = _seed_enriched.get(d.id) or {}
        out[d.id] = d.model_copy(update={k: v for k, v in e.items() if v is not None})
    seed_place_ids = {v.get("place_id"): k for k, v in _seed_enriched.items() if v}
    seed_list = list(out.values())
    for cat, places in zip(labels, results[:-1]):
        for p in places:
            if p["id"] in seed_place_ids and seed_place_ids[p["id"]] in out:
                continue  # already listed via the curated seed entry
            if "lodging" in p.get("types", []) and p.get("primaryType") not in _TYPE_TO_CAT:
                continue  # hotels that also serve food are not "restaurants to visit"
            d = from_place(p)
            twin = d and next((s for s in seed_list if s.category == d.category
                               and haversine_m(s.lat, s.lon, d.lat, d.lon) < 1500), None)
            if twin:   # same place as a curated seed: keep the seed, borrow Google's photo/rating
                out[twin.id] = twin.model_copy(update={k: getattr(d, k) for k in
                                                       ("photo", "rating", "rating_count", "place_id", "open_now", "address")
                                                       if getattr(twin, k) is None and getattr(d, k) is not None})
                continue
            if d and d.id not in out:
                if cat == "medina":
                    d.category = "medina"
                out[d.id] = d
    trace.step("Candidates gathered", total=len(out), seeds=len(seeds),
               google={lab: len(res) for lab, res in zip(labels, results[:-1])})
    return list(out.values())


def assess(d: Destination) -> dict:
    hits = store.near(d.lat, d.lon, CHECK_RADIUS_M)
    status = store.status_of([h["event"] for h in hits])
    reasons = [{"id": h["event"].id, "type": h["event"].type, "severity": h["event"].severity,
                "title": h["event"].title, "distance_m": h["distance_m"],
                "confidence": h["event"].confidence, "source": h["event"].source,
                "observed_at": h["event"].observed_at} for h in hits[:5]]
    return {"status": status, "reasons": reasons}


def _weather_nearby(d: Destination) -> bool:
    return any(h["event"].type in ("storm", "wind", "heat") and h["event"].severity != "info"
               for h in store.near(d.lat, d.lon, 10_000))


def score_breakdown(d: Destination, lat, lon, interests: list[str], status: str) -> dict:
    v = d.rating_count or 0
    if d.rating:
        bayes = (v / (v + 40)) * d.rating + (40 / (v + 40)) * 4.3
    else:
        bayes = 4.3 if d.source == "seed" else 3.9
    quality = max(0.0, min(1.0, (bayes - 3) / 2))
    popularity = min(1.0, math.log10(v + 1) / 4) if v else (0.6 if d.source == "seed" else 0.2)
    interest = 1.0 if d.category in interests else (0.5 if not interests else 0.3)
    km = haversine_m(lat, lon, d.lat, d.lon) / 1000
    proximity = math.exp(-km / PROX_SCALE_KM.get(d.category, 40))
    open_f = 1.0 if d.open_now else 0.55 if d.open_now is False else 0.9
    outdoor = CATEGORIES.get(d.category, ([], True))[1]
    weather = (0.75 if outdoor else 1.05) if _weather_nearby(d) else 1.0
    base = 0.30 * quality + 0.15 * popularity + 0.30 * interest + 0.25 * proximity
    score = round(100 * base * SAFETY[status] * open_f * weather, 1)
    return {"score": score, "quality": round(quality, 2), "bayes_rating": round(bayes, 2),
            "popularity": round(popularity, 2), "interest": interest, "km": round(km, 1),
            "proximity": round(proximity, 2), "safety": SAFETY[status], "open": open_f, "weather": weather,
            "outdoor": outdoor}


def why(d: Destination, b: dict, interests: list[str], status: str) -> list[dict]:
    out = []
    if d.category in interests:
        out.append({"k": "interest", "v": d.category})
    if d.rating:
        out.append({"k": "rating", "v": d.rating, "n": d.rating_count or 0})
    if d.open_now is True:
        out.append({"k": "open"})
    elif d.open_now is False:
        out.append({"k": "closed"})
    if b["weather"] > 1:
        out.append({"k": "indoor_weather"})
    elif b["weather"] < 1:
        out.append({"k": "outdoor_weather"})
    out.append({"k": "status", "v": status})
    return out


def diversify(items: list[dict]) -> list[dict]:
    left, picked, counts = sorted(items, key=lambda x: -x["score"]), [], {}
    while left:
        best = max(left, key=lambda x: x["score"] * 0.85 ** counts.get(x["category"], 0))
        left.remove(best)
        counts[best["category"]] = counts.get(best["category"], 0) + 1
        picked.append(best)
    return picked


@router.get("/recommend")
async def recommend(lat: float, lon: float, interests: str = "", max_km: float = 150,
                    limit: int = 40, lang: str = "en"):
    ints = [i for i in interests.split(",") if i]
    with trace.span("calc", "Recommend places", lat=round(lat, 4), lon=round(lon, 4), interests=ints,
                    formula="100*(0.30*quality+0.15*popularity+0.30*interest+0.25*proximity)*safety*open*weather") as t:
        results, avoided = [], []
        for d in await candidates(lat, lon, max_km, ints, lang):
            a = assess(d)
            b = score_breakdown(d, lat, lon, ints, a["status"])
            item = {**d.model_dump(), **a, "distance_km": b["km"], "score": b["score"],
                    "breakdown": b, "why": why(d, b, ints, a["status"])}
            (avoided if a["status"] == "avoid" else results).append(item)
        ranked = diversify(results)[:limit]
        t.step("Ranked (after diversity pass)", top=[
            {"name": x["name"], "cat": x["category"], "score": x["score"], "status": x["status"],
             **{k: x["breakdown"][k] for k in ("quality", "popularity", "interest", "proximity", "open", "weather")}}
            for x in ranked[:15]])
        if avoided:
            t.step("Hidden from recommendations (status avoid)",
                   places=[{"name": x["name"], "because": x["reasons"][0]["title"] if x["reasons"] else ""} for x in avoided])
        t.set(recommended=len(ranked), avoid=len(avoided))
    return {"recommended": ranked, "avoid_now": avoided, "data_sources": runner.SOURCE_HEALTH}


@router.get("/check")
async def check(lat: float, lon: float, name: str = "destination", category: str = "sight"):
    """Status of any chosen place + 3 similar, safer alternatives when it isn't clear."""
    with trace.span("calc", f"Check destination: {name}", lat=round(lat, 4), lon=round(lon, 4),
                    rule="avoid = danger/critical with confidence >= 0.5 within 3 km; caution = any warning") as t:
        runner.watch(f"user-{lat:.3f}-{lon:.3f}", name, lat, lon)
        target = Destination(id="target", name=name, lat=lat, lon=lon, category=category)
        a = assess(target)
        t.step(f"Status: {a['status']}", reasons=[f"{r['title']} ({r['severity']}, {r['confidence']:.0%}, "
                                                  f"{r['distance_m']} m, {r['source']})" for r in a["reasons"]])
        alternatives = []
        if a["status"] != "clear":
            for d in await candidates(lat, lon, 80, [category] if category in CATEGORIES else None):
                if haversine_m(lat, lon, d.lat, d.lon) < 2000:
                    continue
                da = assess(d)
                if da["status"] == "clear":
                    km = haversine_m(lat, lon, d.lat, d.lon) / 1000
                    same = d.category == category
                    alternatives.append({**d.model_dump(), "status": "clear", "distance_km": round(km, 1),
                                         "why": ("Same kind of place" if same else "No reported issues right now")
                                                + f", {km:.0f} km from {name}",
                                         "same_kind": same, "_rank": (0 if same else 1, -(d.rating or 4) , km)})
            alternatives.sort(key=lambda x: x.pop("_rank"))
            t.step("Alternatives (same kind first, then rating, then distance)",
                   picked=[x["name"] for x in alternatives[:3]])
    return {**a, "alternatives": alternatives[:3]}
