"""
Flood reports -> live 3D flood zones.

Report = photo (vision model picks WHERE the waterline sits on a known object;
plain code converts that anchor to cm — the model never invents numbers)
      or body level ("water is at my knee": fastest and often most reliable).
Reports within 300 m / 3 h are fused into one zone: recency+confidence weighted
median depth, rising/falling trend (weighted least squares, cm/h), minutes until
the next danger level. Zones are published as HazardEvent(type="flood").
Photos are analysed in memory and never stored.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import config, llm, store, trace
from app.reports import trust
from app.security import require_admin
from app.geo import haversine_m
from app.models import HazardEvent, utcnow

log = logging.getLogger("flood")
DATA_DIR = config.DATA_DIR

# ─── Anchors: where the waterline sits -> depth in cm ────────────────────────
# Discrete anchors are far more reliable for a vision model than free numbers.
ANCHORS_CM: dict[str, float] = {
    "wet_road_no_depth": 2,
    "below_kerb": 8,
    "kerb_top": 15,
    "door_step": 20,
    "person_ankle": 10,
    "person_mid_calf": 30,
    "person_knee": 50,
    "person_thigh": 75,
    "person_waist": 100,
    "person_chest": 130,
    "car_tyre_bottom_third": 20,
    "car_tyre_half": 33,
    "car_tyre_top": 65,
    "car_door_bottom": 45,
    "car_bonnet": 90,
    "car_roof": 150,
    "door_handle": 100,
    "window_sill": 90,
    "ground_floor_ceiling": 250,
}

# Danger levels — based on the "turn around, don't drown" rule of thumb:
# ~15 cm of moving water can knock an adult down, ~30 cm floats a car,
# ~60 cm sweeps most vehicles away.
LEVELS = [  # (max_cm, level, severity, label)
    (15, "ankle", "warning", "Ankle-deep — walk carefully"),
    (30, "shin", "danger", "Shin-deep — don't walk in moving water"),
    (60, "knee_car", "critical", "Knee-deep — cars can float, don't drive"),
    (1e9, "deadly", "critical", "Life-threatening — stay away"),
]


def level_for(depth_cm: float) -> tuple[str, str, str]:
    for max_cm, level, sev, label in LEVELS:
        if depth_cm < max_cm:
            return level, sev, label
    return LEVELS[-1][1:]


# ─── Vision analysis ─────────────────────────────────────────────────────────
VISION_PROMPT = f"""You are a flood-depth assessor. Look at the photo.
Decide if it shows standing or flowing flood water in a street/building.
If yes, find the clearest reference object touching the water and choose the
anchor that best matches where the WATERLINE sits. Allowed anchors:
{", ".join(ANCHORS_CM)}.
Also list visible dangers (e.g. fast current, debris, submerged manhole,
electric cables, stranded car). Reply with ONLY this JSON:
{{"is_flood_scene": true|false, "anchor": "<one allowed anchor or null>",
 "reference_object": "<short>", "flowing_water": true|false,
 "visible_dangers": ["..."], "confidence": 0.0-1.0, "reason": "<one sentence>"}}"""


def _shrink_jpeg(raw: bytes, max_side: int = 768) -> bytes:
    from PIL import Image  # installed via qrcode[pil]
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def analyze_photo(raw: bytes) -> dict:
    """-> {ok, depth_cm?, anchor?, confidence, flowing, dangers, reason, model}. Never raises."""
    if not llm.available():
        return {"ok": False, "reason": "vision model not configured", "model": None}
    try:
        b64 = base64.b64encode(_shrink_jpeg(raw)).decode()
    except Exception:
        return {"ok": False, "reason": "unreadable image", "model": None}
    text = await llm.chat([{"role": "user", "content": [
        {"type": "text", "text": VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        model=config.VISION_MODEL, max_tokens=400, temperature=0.1, timeout=45, purpose="flood photo: read the waterline")
    out = llm.extract_json(text)
    trace.step("Vision model answer", answer=out if out is not None else text)
    if not isinstance(out, dict):
        return {"ok": False, "reason": "analysis failed", "model": config.VISION_MODEL}
    anchor = out.get("anchor")
    conf = float(out.get("confidence") or 0.5)
    if not out.get("is_flood_scene") or anchor not in ANCHORS_CM:
        return {"ok": False, "reason": out.get("reason") or "no clear waterline found",
                "model": config.VISION_MODEL}
    trace.step(f"Anchor '{anchor}' -> {ANCHORS_CM[anchor]} cm (fixed table, the AI never gives a number)",
               table=ANCHORS_CM)
    return {"ok": True, "anchor": anchor, "depth_cm": ANCHORS_CM[anchor],
            "confidence": max(0.05, min(0.95, conf)), "flowing": bool(out.get("flowing_water")),
            "dangers": out.get("visible_dangers") or [], "reference_object": out.get("reference_object"),
            "reason": out.get("reason"), "model": config.VISION_MODEL}


# ─── Fusion: reports -> flood zones ──────────────────────────────────────────
@dataclass
class Report:
    lat: float
    lon: float
    depth_cm: float
    confidence: float
    at: datetime
    method: str                 # "photo" | "body" | "web" | "replay"
    flowing: bool = False
    dangers: list[str] = field(default_factory=list)
    note: str = ""
    evidence_url: str | None = None   # web items only (thumbnail); user photos are never stored
    source_url: str | None = None


@dataclass
class Zone:
    id: str
    reports: list[Report] = field(default_factory=list)
    simulated: bool = False
    place: str = ""


_zones: dict[str, Zone] = {}
_latest_seen: datetime | None = None   # lets the replay run on virtual time
JOIN_RADIUS_M = 300
JOIN_WINDOW = timedelta(hours=3)
HALF_LIFE_MIN = 20   # rising water: trust recent reports much more
SINGLE_REPORT_CAP = 0.45


def _now() -> datetime:
    real = utcnow()
    return max(real, _latest_seen) if _latest_seen else real


def _centroid(reports: list[Report]) -> tuple[float, float]:
    return (sum(r.lat for r in reports) / len(reports),
            sum(r.lon for r in reports) / len(reports))


def _weights(reports: list[Report], now: datetime) -> list[float]:
    return [r.confidence * 0.5 ** (max(0.0, (now - r.at).total_seconds() / 60) / HALF_LIFE_MIN)
            for r in reports]


def _weighted_median(values: list[float], weights: list[float]) -> float:
    pairs = sorted(zip(values, weights))
    half, acc = sum(weights) / 2, 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def _trend_cm_per_h(reports: list[Report], weights: list[float]) -> float | None:
    """Weighted least-squares slope of depth over time. None if not enough spread."""
    if len(reports) < 2:
        return None
    t0 = min(r.at for r in reports)
    xs = [(r.at - t0).total_seconds() / 3600 for r in reports]
    if max(xs) - min(xs) < 10 / 60:
        return None
    sw = sum(weights)
    mx = sum(w * x for w, x in zip(weights, xs)) / sw
    my = sum(w * r.depth_cm for w, r in zip(weights, reports)) / sw
    num = sum(w * (x - mx) * (r.depth_cm - my) for w, x, r in zip(weights, xs, reports))
    den = sum(w * (x - mx) ** 2 for w, x in zip(weights, xs))
    return None if den == 0 else num / den


def _publish(zone: Zone) -> HazardEvent:
    now = _now()
    reps = zone.reports
    w = _weights(reps, now)
    depth = _weighted_median([r.depth_cm for r in reps], w)
    trend = _trend_cm_per_h(reps, w)
    level, severity, label = level_for(depth)
    if any(r.flowing for r in reps[-3:]) and severity == "danger":
        severity, label = "critical", label + " (fast current reported)"
    lat, lon = _centroid(reps)
    spread = max(haversine_m(lat, lon, r.lat, r.lon) for r in reps)
    corroboration = 1 - math.prod(1 - r.confidence for r in reps[-6:])
    if len(reps) == 1:
        # One unverified report can never cause "avoid" on its own (status rule): cap below 0.5.
        corroboration = min(corroboration, SINGLE_REPORT_CAP)

    minutes_to_next = None
    if trend and trend > 1:
        nxt = next((m for m, *_ in LEVELS if m > depth and m < 1e9), None)
        if nxt:
            minutes_to_next = round((nxt - depth) / trend * 60)

    trace.step(f"Fuse zone {zone.id}: {len(reps)} report(s)",
               reports=[{"cm": r.depth_cm, "conf": round(r.confidence, 2), "method": r.method,
                         "min_ago": round((now - r.at).total_seconds() / 60), "weight": round(wi, 3)}
                        for r, wi in zip(reps[-12:], w[-12:])],
               weight_rule=f"confidence x 0.5^(age_min / {HALF_LIFE_MIN})",
               weighted_median_cm=depth, trend_cm_per_h=None if trend is None else round(trend, 1),
               level=level, severity=severity, minutes_to_next_level=minutes_to_next,
               corroboration=f"1 - prod(1 - conf of last 6) = {corroboration:.2f}",
               radius_m=round(max(150.0, spread + 100)))
    dangers = sorted({d for r in reps[-5:] for d in r.dangers})
    trend_txt = "" if trend is None else (
        f" · rising {trend:.0f} cm/h" if trend > 1 else
        f" · falling {abs(trend):.0f} cm/h" if trend < -1 else " · stable")
    return store.upsert(HazardEvent(
        id=zone.id, type="flood", severity=severity,
        title=f"{label}{trend_txt}",
        description=(zone.place + " — " if zone.place else "") +
                    f"~{depth:.0f} cm from {len(reps)} report(s)." +
                    (f" Dangers: {', '.join(dangers)}." if dangers else ""),
        lat=lat, lon=lon, radius_m=max(150.0, spread + 100),
        confidence=round(min(0.95, corroboration), 2),
        source="replay" if zone.simulated else ("web" if all(r.method == "web" for r in reps) else "crowd"),
        is_simulated=zone.simulated,
        observed_at=max(r.at for r in reps),
        reports_count=len(reps),
        data={"depth_cm": round(depth), "level": level,
              "trend_cm_per_h": None if trend is None else round(trend, 1),
              "minutes_to_next_level": minutes_to_next,
              "dangers": dangers, "kind": "observed",
              "methods": {m: sum(r.method == m for r in reps) for m in {r.method for r in reps}},
              "evidence": [{"thumb": r.evidence_url, "url": r.source_url, "at": r.at.isoformat()}
                           for r in reps if r.evidence_url][-6:],
              "report_points": [[r.lat, r.lon, r.depth_cm] for r in reps[-20:]]},
    ))


def add_report(rep: Report, simulated: bool = False, place: str = "") -> HazardEvent:
    global _latest_seen
    _latest_seen = max(_latest_seen, rep.at) if _latest_seen else rep.at
    best, best_d = None, float("inf")
    for z in _zones.values():
        if z.simulated != simulated or rep.at - z.reports[-1].at > JOIN_WINDOW:
            continue
        d = haversine_m(rep.lat, rep.lon, *_centroid(z.reports))
        if d < JOIN_RADIUS_M and d < best_d:
            best, best_d = z, d
    if best is None:
        best = Zone(id=f"flood-{uuid.uuid4().hex[:8]}", simulated=simulated, place=place)
        _zones[best.id] = best
        trace.step(f"New flood zone {best.id} (no zone within {JOIN_RADIUS_M} m / 3 h)")
    else:
        trace.step(f"Joined zone {best.id}, {best_d:.0f} m from its centre")
    best.reports.append(rep)
    return _publish(best)


# ─── API ─────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/flood", tags=["flood"])


@router.get("/anchors")
def anchors():
    """Body-level buttons for the report UI."""
    return {"body_levels": {k: v for k, v in ANCHORS_CM.items() if k.startswith("person_")},
            "levels": [{"max_cm": m if m < 1e9 else None, "level": l, "severity": s, "label": t}
                       for m, l, s, t in LEVELS]}


@router.post("/report")
async def report(
    lat: float = Form(...),
    lon: float = Form(...),
    body_level: str | None = Form(None),     # e.g. "person_knee" (no photo needed)
    note: str = Form(""),
    device_id: str = Form("anon"),
    accuracy_m: float | None = Form(None),     # GPS accuracy from the phone
    photo: UploadFile | None = File(None),
):
    """Photo and/or body-level report. If the photo can't be read, the response
    says needs_manual=true and the UI shows the body-level buttons instead."""
    with trace.span("report", "Flood report", has_photo=photo is not None, body_level=body_level,
                    lat=round(lat, 4), lon=round(lon, 4), accuracy_m=accuracy_m) as t:
        out = await _report(lat, lon, body_level, note, device_id, accuracy_m, photo)
        t.set(accepted=out.get("accepted"), reason=out.get("reason"))
        if not out.get("accepted"):
            t.rec["ok"] = False
        return out


async def _report(lat, lon, body_level, note, device_id, accuracy_m, photo, simulated: bool = False,
                  skip_exif: bool = False):
    ok, why = trust.allow(device_id, "flood")
    if not ok:
        raise HTTPException(429, why)
    analysis = None
    if photo is not None:
        raw = await photo.read()
        if len(raw) > 15_000_000:
            raise HTTPException(413, "photo too large")
        fresh, reason = (True, "") if skip_exif else trust.exif_check(raw, lat, lon)
        trace.step("Photo freshness/location check (EXIF)", passed=fresh, reason=reason or "ok", skipped=skip_exif)
        if not fresh:
            return {"accepted": False, "needs_manual": False, "reason": reason}
        analysis = await analyze_photo(raw)   # photo bytes are discarded after this
        del raw

    if analysis and analysis["ok"]:
        rep = Report(lat, lon, analysis["depth_cm"], analysis["confidence"], utcnow(),
                     "photo", analysis["flowing"], analysis["dangers"], note)
    elif body_level in ANCHORS_CM:
        rep = Report(lat, lon, ANCHORS_CM[body_level], 0.8, utcnow(), "body", note=note)
    else:
        return {"accepted": False, "needs_manual": True,
                "reason": (analysis or {}).get("reason", "no photo or body level given"),
                "body_levels": [k for k in ANCHORS_CM if k.startswith("person_")]}

    base = rep.confidence
    rep.confidence *= trust.gps_factor(accuracy_m) * trust.device_factor(device_id)
    trace.step("Trust weighting", base_confidence=base, gps_factor=trust.gps_factor(accuracy_m),
               device_reputation=trust.device_factor(device_id), final=round(rep.confidence, 3))
    trust.record(device_id, "flood")
    event = add_report(rep, simulated=simulated)
    return {"accepted": True, "method": rep.method, "depth_cm": rep.depth_cm,
            "analysis": analysis, "zone": event}


# ─── Replay a past flood as if live (for the demo video) ─────────────────────
_replay_task: asyncio.Task | None = None


async def _run_replay(items: list[dict], speed: float):
    global _latest_seen
    origin = utcnow()
    prev_min = 0.0
    for it in sorted(items, key=lambda x: x["minute"]):
        await asyncio.sleep(max(0.0, (it["minute"] - prev_min) * 60 / speed))
        prev_min = it["minute"]
        add_report(Report(it["lat"], it["lon"], ANCHORS_CM[it["anchor"]],
                          it.get("confidence", 0.7),
                          origin + timedelta(minutes=it["minute"]), "replay",
                          it.get("flowing", False), it.get("dangers", []), it.get("note", "")),
                   simulated=True, place=it.get("place", ""))


def load_replay(file: str = "flood_replay.json", center: tuple[float, float] | None = None) -> list[dict]:
    """Replay items; with center=(lat, lon) the whole flood is moved there (test it where you are)."""
    path = DATA_DIR / Path(file).name
    if not path.exists():
        raise HTTPException(404, f"{path.name} not found in data/")
    items = json.loads(path.read_text(encoding="utf-8"))
    if center:
        clat = sum(i["lat"] for i in items) / len(items)
        clon = sum(i["lon"] for i in items) / len(items)
        items = [{**i, "lat": i["lat"] - clat + center[0], "lon": i["lon"] - clon + center[1],
                  "place": "Simulated flood near you"} for i in items]
    return items


def start_replay(items: list[dict], speed: float) -> None:
    global _replay_task
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
    _replay_task = asyncio.create_task(_run_replay(items, speed))


@router.post("/replay/start", dependencies=[Depends(require_admin)])
async def replay_start(file: str = "flood_replay.json", speed: float = 60):
    """speed=60 -> 1 simulated hour plays in 1 real minute. All events are is_simulated."""
    items = load_replay(file)
    start_replay(items, speed)
    trace.event("sim", f"Flood replay started ({len(items)} reports, x{speed})")
    return {"started": True, "reports": len(items), "speed": speed}


@router.post("/replay/reset", dependencies=[Depends(require_admin)])
def replay_reset():
    global _replay_task, _latest_seen
    if _replay_task and not _replay_task.done():
        _replay_task.cancel()
    for zid in [z.id for z in _zones.values() if z.simulated]:
        _zones.pop(zid, None)
        store.remove(zid)
    _latest_seen = None
    return {"reset": True}
