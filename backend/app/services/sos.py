"""SOS: everything a tourist needs in the worst 60 seconds of their trip.

POST /api/sos returns, in one call:
  - the right emergency numbers for the country (tap-to-call on the phone)
  - the exact location as address + Plus Code + GPS
  - an EMERGENCY CARD in Arabic + French (+ the tourist's language) to show or
    play aloud to the operator/locals — deterministic templates, no AI needed,
    so it works even when the LLM is down. The AI only translates the free-text note.
  - nearest open hospital / pharmacy / police station (Google Places)
  - a share message for WhatsApp/SMS to an emergency contact
It also posts an anonymous hazard (accident/fire/flood) so other travellers are warned.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from app import config, llm, store, trace
from app.models import HazardEvent
from app.services.google import places_nearby, reverse_geocode

router = APIRouter(prefix="/api/sos", tags=["sos"])

KINDS = {
    #  kind        : (ar, fr, en, which number, public hazard type or None)
    "accident":    ("حادث مرور", "accident de la route", "road accident", "civil_protection", "accident"),
    "medical":     ("حالة طبية طارئة", "urgence médicale", "medical emergency", "ambulance", None),
    "flood_stuck": ("عالق بسبب الفيضانات", "bloqué par une inondation", "trapped by flooding", "civil_protection", "flood"),
    "fire":        ("حريق", "incendie", "fire", "civil_protection", "fire"),
    "crime":       ("تعرضت لاعتداء أو سرقة", "agression ou vol", "assault or theft", "police", None),
    "lost":        ("أنا تائه", "je suis perdu", "I am lost", "police", None),
}


class SOSRequest(BaseModel):
    kind: str
    lat: float
    lon: float
    people: int = 1
    injured: bool = False
    note: str = ""
    lang: str = "en"          # tourist's language for their own copy


def _card(kind: str, people: int, injured: bool, where: dict, lat: float, lon: float) -> dict:
    ar, fr, en, *_ = KINDS[kind]
    place = " ".join(x for x in (where.get("address"), where.get("plus_code")) if x)
    gps = f"{lat:.5f}, {lon:.5f}"
    # Latin address / GPS inside Arabic text: wrap in left-to-right isolates so bidi keeps them in order
    ar_place = f" المكان: \u2066{place}\u2069." if place else ""
    fr_place = f" Lieu : {place}." if place else ""
    en_place = f" Location: {place}." if place else ""
    return {
        "ar": (f"حالة طوارئ: {ar}. عدد الأشخاص: {people}."
               + (" يوجد مصابون." if injured else "")
               + f"{ar_place} الإحداثيات: \u2066{gps}\u2069. أنا سائح ولا أتكلم العربية جيداً."),
        "fr": (f"Urgence : {fr}. Nombre de personnes : {people}."
               + (" Il y a des blessés." if injured else "")
               + f"{fr_place} GPS : {gps}. Je suis touriste et je parle mal français."),
        "en": (f"Emergency: {en}. People: {people}." + (" There are injured people." if injured else "")
               + f"{en_place} GPS: {gps}."),
    }


def _brief_place(p: dict, lat: float, lon: float) -> dict:
    from app.geo import haversine_m
    loc = p.get("location", {})
    return {"name": (p.get("displayName") or {}).get("text"), "address": p.get("formattedAddress"),
            "phone": p.get("nationalPhoneNumber"),
            "open_now": (p.get("currentOpeningHours") or {}).get("openNow"),
            "lat": loc.get("latitude"), "lon": loc.get("longitude"),
            "distance_m": round(haversine_m(lat, lon, loc.get("latitude", lat), loc.get("longitude", lon)))}


@router.post("")
async def sos(req: SOSRequest):
    with trace.span("agent", f"SOS: {req.kind}", people=req.people, injured=req.injured, lang=req.lang,
                    rule="card = fixed AR/FR templates (works without AI); AI only translates the free-text note") as t:
        out = await _sos(req)
        t.set(primary_number=out["primary_number"], public_hazard=out["public_hazard_id"],
              address=out["location"].get("address"), nearest={k: len(v) for k, v in out["nearest"].items()},
              note_translated=out["note_translations"] is not None)
        return out


async def _sos(req: SOSRequest):
    kind = req.kind if req.kind in KINDS else "medical"
    numbers = config.PROFILE["emergency_numbers"]
    where, hosp, pharm, police = await asyncio.gather(
        reverse_geocode(req.lat, req.lon, "fr"),
        places_nearby(req.lat, req.lon, 15000, ["hospital"], 3, rank_by_distance=True),
        places_nearby(req.lat, req.lon, 5000, ["pharmacy"], 3, rank_by_distance=True),
        places_nearby(req.lat, req.lon, 10000, ["police"], 2, rank_by_distance=True),
    )
    card = _card(kind, req.people, req.injured, where, req.lat, req.lon)
    trace.step("Location resolved", address=where.get("address"), plus_code=where.get("plus_code"))

    note_translations = None
    if req.note.strip():
        out = await llm.chat_json(
            "Translate the traveller's emergency note. Keep it short and literal.",
            f'Note: "{req.note}"\nReturn {{"ar": "...", "fr": "...", "en": "..."}}', max_tokens=300,
            purpose="SOS: translate the traveller's note")
        if isinstance(out, dict):
            note_translations = out
            for k in ("ar", "fr", "en"):
                if out.get(k):
                    card[k] += f" — {out[k]}"

    hazard = None
    public_type = KINDS[kind][4]
    if public_type:  # anonymous public warning: type + approximate place only
        hazard = store.upsert(HazardEvent(
            type=public_type, severity="danger", title=f"SOS: {KINDS[kind][2]} reported",
            description="Emergency reported by a traveller. Avoid the area if you can.",
            lat=round(req.lat, 3), lon=round(req.lon, 3), radius_m=400, confidence=0.5, source="sos"))

    mine = None   # the tourist's own copy when it is not ar/fr/en
    if req.lang not in ("ar", "fr", "en"):
        from app.services.language import translate
        texts, provider = await translate([card["en"]], req.lang)
        if provider != "none":
            mine = texts[0]
    maps_link = f"https://maps.google.com/?q={req.lat:.5f},{req.lon:.5f}"
    return {
        "primary_number": numbers[KINDS[kind][3]],
        "numbers": numbers,
        "location": {**where, "lat": req.lat, "lon": req.lon, "maps_link": maps_link},
        "card": card,                      # show big on screen + read aloud (ar / fr voices)
        "card_mine": mine,
        "speak": [{"lang": "ar", "text": card["ar"]}, {"lang": "fr", "text": card["fr"]}],
        "note_translations": note_translations,
        "nearest": {"hospital": [_brief_place(p, req.lat, req.lon) for p in hosp],
                    "pharmacy": [_brief_place(p, req.lat, req.lon) for p in pharm],
                    "police": [_brief_place(p, req.lat, req.lon) for p in police]},
        "share_text": f"EMERGENCY: {KINDS[kind][2]}. I need help. My location: {maps_link} "
                      f"({where.get('plus_code') or ''}). Emergency number here: {numbers[KINDS[kind][3]]}",
        "public_hazard_id": hazard.id if hazard else None,
    }
