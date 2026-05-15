"""Location helpers for on-demand distance sorting."""

from __future__ import annotations

import math
import re


# Small seed gazetteer for MVP tests and common first searches. Unknown locations
# still pass through to source-side location search, but distances are omitted.
GAZETTEER: dict[str, tuple[float, float]] = {
    "shanghai": (31.2304, 121.4737),
    "shanghai, china": (31.2304, 121.4737),
    "hangzhou": (30.2741, 120.1551),
    "hangzhou, china": (30.2741, 120.1551),
    "hangzhou, zhejiang": (30.2741, 120.1551),
    "beijing": (39.9042, 116.4074),
    "hong kong": (22.3193, 114.1694),
    "new york": (40.7128, -74.0060),
    "boston": (42.3601, -71.0589),
    "london": (51.5072, -0.1276),
    "sydney": (-33.8688, 151.2093),
    "melbourne": (-37.8136, 144.9631),
    "tokyo": (35.6762, 139.6503),
    "seoul": (37.5665, 126.9780),
    "singapore": (1.3521, 103.8198),
}


def resolve_location(location_text: str) -> dict[str, object]:
    text = (location_text or "").strip()
    if not text:
        return {"query_text": "", "lat": None, "lon": None, "method": "none"}

    coordinate_match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", text)
    if coordinate_match:
        lat = float(coordinate_match.group(1))
        lon = float(coordinate_match.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return {"query_text": text, "lat": lat, "lon": lon, "method": "coordinates"}

    coords = GAZETTEER.get(text.lower())
    if coords:
        return {"query_text": text, "lat": coords[0], "lon": coords[1], "method": "local_gazetteer"}

    return {"query_text": text, "lat": None, "lon": None, "method": "source_location_text"}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
