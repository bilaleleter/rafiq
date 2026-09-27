"""Shared data contract. HazardEvent is THE object every feature reads and writes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

HazardType = Literal["flood", "fire", "power", "water", "storm", "wind", "heat",
                     "earthquake", "accident", "road", "health", "crowd", "other"]
Severity = Literal["info", "warning", "danger", "critical"]
Status = Literal["clear", "caution", "avoid", "unknown"]
SEVERITY_RANK = {"info": 0, "warning": 1, "danger": 2, "critical": 3}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HazardEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    type: HazardType
    severity: Severity
    title: str                              # short, shown on the map badge
    description: str = ""
    lat: float
    lon: float
    radius_m: float = 500
    confidence: float = Field(0.6, ge=0, le=1)
    source: str = "unknown"                 # "open-meteo", "firms", "usgs", "news", "crowd", "sos", "demo"
    source_url: str | None = None
    is_simulated: bool = False              # MUST be true for demo data
    observed_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    reports_count: int = 1
    votes_still_there: int = 0
    votes_gone: int = 0
    data: dict = Field(default_factory=dict)  # type-specific details (flood: depth_cm, trend...)


class LatLon(BaseModel):
    lat: float
    lon: float


class Destination(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    category: str = "sight"                 # see destinations.CATEGORIES
    rating: float | None = None
    rating_count: int | None = None
    source: str = "seed"                    # seed | google_places
    place_id: str | None = None
    photo: str | None = None                # Places photo resource name -> /api/places/photo?name=
    address: str | None = None
    open_now: bool | None = None
    primary_type: str | None = None
    summary: str | None = None              # Google editorial summary (not AI-written by us)
    price_level: str | None = None
