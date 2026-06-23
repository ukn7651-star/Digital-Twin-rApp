"""Fetch and parse building footprints from the OpenStreetMap Overpass API.

The network fetch (`fetch_overpass_json`) is kept separate from the parser
(`parse_buildings`) so the parsing can be unit-tested offline with canned JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from dtrapp.config import BoundingBox, SimulationConfig


class OverpassError(RuntimeError):
    """Raised when OSM data cannot be fetched or parsed. No fallback follows."""


@dataclass
class Building:
    """A building footprint in WGS84 plus an extrusion height."""

    outline_latlon: list[tuple[float, float]]  # (lat, lon) ring, not closed
    height_m: float
    osm_id: int


def build_query(bbox: BoundingBox, timeout_s: int) -> str:
    """Overpass QL query for all buildings within the bounding box."""
    bb = bbox.as_overpass_bbox()
    return (
        f"[out:json][timeout:{timeout_s}];"
        f'(way["building"]({bb});relation["building"]({bb}););'
        f"out body;>;out skel qt;"
    )


def fetch_overpass_json(bbox: BoundingBox, config: SimulationConfig) -> dict:
    """Query the Overpass API. Raises OverpassError on any failure."""
    query = build_query(bbox, config.overpass_timeout_s)
    try:
        resp = requests.post(
            config.overpass_url,
            data={"data": query},
            headers={"User-Agent": "dtrapp/0.1 (OSM building fetch)"},
            timeout=config.overpass_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise OverpassError(f"Failed to fetch OSM data: {exc}") from exc
    except ValueError as exc:
        raise OverpassError(f"Overpass returned non-JSON: {exc}") from exc


def _parse_height(tags: dict, config: SimulationConfig) -> float:
    """Derive an extrusion height (m): explicit height, else levels, else default."""
    for key, scale in (("height", 1.0), ("building:levels", config.meters_per_level)):
        raw = tags.get(key)
        if raw is None:
            continue
        match = re.search(r"[-+]?\d*\.?\d+", str(raw))
        if match:
            value = float(match.group())
            if value > 0:
                return value * scale
    return config.default_building_height_m


def parse_buildings(data: dict, config: SimulationConfig) -> list[Building]:
    """Parse an Overpass JSON payload into Buildings (ways + relation outers)."""
    elements = data.get("elements")
    if elements is None:
        raise OverpassError("Overpass response has no 'elements' field")

    nodes: dict[int, tuple[float, float]] = {}
    ways: dict[int, dict] = {}
    relations: list[dict] = []
    for el in elements:
        etype = el.get("type")
        if etype == "node":
            nodes[el["id"]] = (el["lat"], el["lon"])
        elif etype == "way":
            ways[el["id"]] = el
        elif etype == "relation":
            relations.append(el)

    buildings: list[Building] = []
    consumed: set[int] = set()

    for rel in relations:
        tags = rel.get("tags", {})
        if "building" not in tags and tags.get("type") != "multipolygon":
            continue
        height = _parse_height(tags, config)
        for member in rel.get("members", []):
            if member.get("type") == "way" and member.get("role") == "outer":
                wid = member.get("ref")
                ring = _way_ring(ways.get(wid), nodes) if wid in ways else None
                if ring is not None:
                    buildings.append(Building(ring, height, wid))
                    consumed.add(wid)

    for wid, way in ways.items():
        if wid in consumed or "building" not in way.get("tags", {}):
            continue
        ring = _way_ring(way, nodes)
        if ring is not None:
            buildings.append(Building(ring, _parse_height(way["tags"], config), wid))

    return buildings


def _way_ring(way: dict | None, nodes: dict[int, tuple[float, float]]):
    """Resolve a way's node refs into a coordinate ring (>=3 distinct points)."""
    if way is None:
        return None
    coords = [nodes[r] for r in way.get("nodes", []) if r in nodes]
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords if len(coords) >= 3 else None
