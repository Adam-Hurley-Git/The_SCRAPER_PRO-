from __future__ import annotations

from collections.abc import Iterable


BBox = tuple[float, float, float, float]


def subdivide(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> list[BBox]:
    mid_lat = (min_lat + max_lat) / 2
    mid_lon = (min_lon + max_lon) / 2
    return [
        (min_lat, min_lon, mid_lat, mid_lon),
        (min_lat, mid_lon, mid_lat, max_lon),
        (mid_lat, min_lon, max_lat, mid_lon),
        (mid_lat, mid_lon, max_lat, max_lon),
    ]


def cell_size(bbox: BBox) -> float:
    min_lat, min_lon, max_lat, max_lon = bbox
    return min(max_lat - min_lat, max_lon - min_lon)


def cells_requiring_resume(statuses: Iterable[str]) -> int:
    return sum(1 for status in statuses if status == "running")
