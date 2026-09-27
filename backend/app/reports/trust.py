"""Trust layer for everything people report — keeps crowd data reliable.

- device_id : random UUID the app keeps on the phone (no account, no personal data)
- rate limit: max 1 report of the same type per device per 5 min, 20 per hour overall
- one device = one voice: fusion counts DISTINCT devices, never repeated taps
- GPS accuracy: a fix worse than 200 m lowers confidence
- photo freshness: if the photo has EXIF data, it must be < 3 h old and taken
  within 2 km of the reported position (stops re-uploading old/foreign photos)
- device reputation: devices whose reports get confirmed by others gain weight,
  devices whose reports get voted "gone"/fake lose weight (0.5x - 1.2x)
"""
from __future__ import annotations

import io
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from app.geo import haversine_m

_recent: dict[str, deque] = defaultdict(deque)       # device -> deque[(ts, type)]
_reputation: dict[str, float] = defaultdict(lambda: 1.0)

SAME_TYPE_GAP_S = 300
MAX_PER_HOUR = 20


def allow(device_id: str, kind: str) -> tuple[bool, str]:
    now = time.time()
    q = _recent[device_id]
    while q and now - q[0][0] > 3600:
        q.popleft()
    if len(q) >= MAX_PER_HOUR:
        return False, "Too many reports from this device — try again later."
    if any(t == kind and now - ts < SAME_TYPE_GAP_S for ts, t in q):
        return False, "You already reported this a few minutes ago — thanks!"
    return True, ""


def record(device_id: str, kind: str) -> None:
    _recent[device_id].append((time.time(), kind))


def gps_factor(accuracy_m: float | None) -> float:
    if accuracy_m is None:
        return 0.85
    return 1.0 if accuracy_m <= 50 else 0.9 if accuracy_m <= 200 else 0.6


def device_factor(device_id: str) -> float:
    return _reputation[device_id]


def reward(device_id: str, delta: float) -> None:
    _reputation[device_id] = max(0.5, min(1.2, _reputation[device_id] + delta))


def _gps_from_exif(gps: dict) -> tuple[float, float] | None:
    try:
        def deg(v):
            d, m, s = (float(x) for x in v)
            return d + m / 60 + s / 3600
        lat, lon = deg(gps[2]), deg(gps[4])
        if gps.get(1) == "S":
            lat = -lat
        if gps.get(3) == "W":
            lon = -lon
        return lat, lon
    except Exception:
        return None


def exif_check(raw: bytes, lat: float, lon: float, max_age_h: float = 3) -> tuple[bool, str]:
    """Photos straight from the in-app camera usually have no EXIF (fine).
    Gallery photos usually do — then they must be recent and taken near here."""
    try:
        from PIL import Image
        exif = Image.open(io.BytesIO(raw)).getexif()
    except Exception:
        return True, ""
    if not exif:
        return True, ""
    taken = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
    if taken:
        try:
            t = datetime.strptime(str(taken), "%Y:%m:%d %H:%M:%S")
            # EXIF has no timezone: allow ±14 h slack, then apply the age limit
            age_h = (datetime.now() - t).total_seconds() / 3600
            if age_h > max_age_h + 14:
                return False, f"This photo was taken {age_h / 24:.0f} days ago — please send a photo of the water right now."
        except ValueError:
            pass
    gps = _gps_from_exif(exif.get_ifd(0x8825))
    if gps and haversine_m(lat, lon, *gps) > 2000:
        return False, "This photo was taken somewhere else — please photograph the water where you are."
    return True, ""


def utc_ts() -> datetime:
    return datetime.now(timezone.utc)
