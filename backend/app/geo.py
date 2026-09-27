import math


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_segment_m(lat, lon, a, b) -> float:
    """Distance from point to segment a-b ([lat, lon] each), local flat projection (fine < 50 km)."""
    k = 111_320.0
    c = math.cos(math.radians(lat))
    ax, ay = (a[1] - lon) * k * c, (a[0] - lat) * k
    bx, by = (b[1] - lon) * k * c, (b[0] - lat) * k
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    return math.hypot(ax + t * dx, ay + t * dy)


def decode_polyline(encoded: str) -> list[list[float]]:
    """Google encoded polyline -> [[lat, lon], ...]"""
    coords, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        for is_lng in (False, True):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lng:
                lng += delta
            else:
                lat += delta
        coords.append([lat / 1e5, lng / 1e5])
    return coords


def cluster_points(points: list[tuple[float, float]], radius_m: float) -> list[list[int]]:
    """Greedy clustering -> lists of indices. Good enough for a few hundred points."""
    clusters: list[list[int]] = []
    centers: list[tuple[float, float]] = []
    for i, (la, lo) in enumerate(points):
        for ci, (cla, clo) in enumerate(centers):
            if haversine_m(la, lo, cla, clo) <= radius_m:
                clusters[ci].append(i)
                n = len(clusters[ci])
                centers[ci] = (cla + (la - cla) / n, clo + (lo - clo) / n)
                break
        else:
            clusters.append([i])
            centers.append((la, lo))
    return clusters
