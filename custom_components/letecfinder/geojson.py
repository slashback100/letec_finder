"""Conversion des tracés Letec Finder en GeoJSON."""

from __future__ import annotations

import math
from typing import Any


def _distance(point: list[float], start: list[float], end: list[float]) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    position = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (
        dx * dx + dy * dy
    )
    position = max(0.0, min(1.0, position))
    return math.hypot(
        point[0] - (start[0] + position * dx),
        point[1] - (start[1] + position * dy),
    )


def _simplify(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        farthest = 0.0
        index = -1
        for position in range(start + 1, end):
            distance = _distance(points[position], points[start], points[end])
            if distance > farthest:
                farthest = distance
                index = position
        if index != -1 and farthest > tolerance:
            keep[index] = True
            stack.append((start, index))
            stack.append((index, end))
    return [point for point, kept in zip(points, keep) if kept]


def paths_to_geojson(
    paths: list[list[Any]],
    properties: dict[str, Any] | None = None,
    tolerance: float = 0.0002,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for path in paths:
        coordinates: list[list[float]] = []
        for point in path:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                coordinate = [round(float(point[0]), 5), round(float(point[1]), 5)]
            except (TypeError, ValueError):
                continue
            if not coordinates or coordinate != coordinates[-1]:
                coordinates.append(coordinate)
        if len(coordinates) < 2:
            continue
        coordinates = _simplify(coordinates, tolerance)
        features.append(
            {
                "type": "Feature",
                "properties": dict(properties or {}),
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        )
    return {"type": "FeatureCollection", "features": features}
