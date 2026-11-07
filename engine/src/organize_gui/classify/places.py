"""Offline coarse reverse geocoding: (lat, lon) -> country name, or None."""

from functools import lru_cache
from typing import Optional

from .countries_data import COUNTRIES

_OFFSETS = [(0.0, 0.0)] + [(dx, dy) for step in (0.4, 0.8) for dx, dy in
                           ((step, 0), (-step, 0), (0, step), (0, -step),
                            (step, step), (-step, -step), (step, -step), (-step, step))]


def _inside(x: float, y: float, ring) -> bool:
    inside = False
    count = len(ring) // 2
    j = count - 1
    for i in range(count):
        xi, yi, xj, yj = ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _lookup(lon: float, lat: float) -> Optional[str]:
    for name, (x0, y0, x1, y1), rings in COUNTRIES:
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            inside = False
            for ring in rings:
                if _inside(lon, lat, ring):
                    inside = not inside
            if inside:
                return name
    return None


@lru_cache(maxsize=4096)
def country_for(lat: float, lon: float) -> Optional[str]:
    """Country containing the point; coastal points get a small search radius (1:110m outlines)."""
    for dx, dy in _OFFSETS:
        name = _lookup(round(lon + dx, 2), round(lat + dy, 2))
        if name:
            return name
    return None
