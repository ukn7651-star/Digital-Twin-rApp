"""Fetch and parse building footprints from the OpenStreetMap Overpass API.

The network fetch (`fetch_overpass_json`) is deliberately separated from the
parser (`parse_buildings`) so the parsing logic can be unit-tested offline with
canned Overpass responses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

from dtrapp.config import BoundingBox, GeometryConfig


class OverpassError(RuntimeError):
    """Raised when OSM data cannot be fetched or parsed. No fallback follows."""


@dataclass
class Building:
    """A single building footprint in WGS84 with an extrusion height."""

    outline_latlon: list[tuple[float, float]]  # (lat, lon) ring, not closed
    height_m: float
    osm_id: int


def build_query(bbox: BoundingBox, timeout_s: int) -> str:
    """Construct an Overpass QL query for buildings within the bounding box."""
    bb = bbox.as_overpass_bbox()
    return (
        f"[out:json][timeout:{timeout_s}];"
        f"("
        f'way["building"]({bb});'
        f'relation["building"]({bb});'
        f");"
        f"out body;"
        f">;"
        f"out skel qt;"
    )


def fetch_overpass_json(bbox: BoundingBox, config: GeometryConfig) -> dict:
    """Query the Overpass API and return the parsed JSON response.

    Raises OverpassError on any network/HTTP/decoding failure.
    """
    query = build_query(bbox, config.overpass_timeout_s)
    headers = {
        # Overpass rejects some default clients (HTTP 406); identify ourselves.
        "User-Agent": "dtrapp-digital-twin/0.1 (OSM building fetch)",
        "Accept": "application/json",
    }
    try:
        resp = requests.post(
            config.overpass_url,
            data={"data": query},
            headers=headers,
            timeout=config.overpass_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        raise OverpassError(
            f"Failed to fetch OSM data from {config.overpass_url}: {exc}"
        ) from exc
    except ValueError as exc:  # JSON decode error
        raise OverpassError(f"Overpass returned non-JSON response: {exc}") from exc


def _parse_height(tags: dict, config: GeometryConfig) -> float:
    """Derive an extrusion height (m) from OSM tags, with fallbacks."""
    height = tags.get("height")
    if height is not None:
        match = re.search(r"[-+]?\d*\.?\d+", str(height))
        if match:
            try:
                value = float(match.group())
                if value > 0:
                    return value
            except ValueError:
                pass

    levels = tags.get("building:levels")
    if levels is not None:
        match = re.search(r"[-+]?\d*\.?\d+", str(levels))
        if match:
            try:
                n = float(match.group())
                if n > 0:
                    return n * config.meters_per_level
            except ValueError:
                pass

    return config.default_building_height


def parse_buildings(data: dict, config: GeometryConfig) -> list[Building]:
    """Parse an Overpass JSON payload into a list of Buildings.

    Handles `way` elements with a building tag directly, plus the `outer` rings
    of building `relation` (multipolygon) elements. Inner rings (courtyards) are
    ignored in v1 - a small over-estimate of building footprint area.
    """
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
    consumed_way_ids: set[int] = set()

    # Relations first so we can mark their member ways as consumed.
    for rel in relations:
        tags = rel.get("tags", {})
        if "building" not in tags and tags.get("type") != "multipolygon":
            continue
        height = _parse_height(tags, config)
        for member in rel.get("members", []):
            if member.get("type") == "way" and member.get("role") == "outer":
                wid = member.get("ref")
                way = ways.get(wid)
                if way is None:
                    continue
                ring = _way_ring(way, nodes)
                if ring is not None:
                    buildings.append(Building(ring, height, wid))
                    consumed_way_ids.add(wid)

    for wid, way in ways.items():
        if wid in consumed_way_ids:
            continue
        tags = way.get("tags", {})
        if "building" not in tags:
            continue
        ring = _way_ring(way, nodes)
        if ring is None:
            continue
        height = _parse_height(tags, config)
        buildings.append(Building(ring, height, wid))

    return buildings


def _way_ring(way: dict, nodes: dict[int, tuple[float, float]]):
    """Resolve a way's node refs into a coordinate ring (>=3 distinct points)."""
    refs = way.get("nodes", [])
    coords: list[tuple[float, float]] = []
    for ref in refs:
        coord = nodes.get(ref)
        if coord is not None:
            coords.append(coord)
    # Drop a duplicated closing node if present.
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(coords) < 3:
        return None
    return coords
