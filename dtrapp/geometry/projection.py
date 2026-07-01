"""Local tangent-plane projection (WGS84 lat/lon <-> local ENU meters).

The Mitsuba scene, the cells, and the UEs all live in a single local metric
frame: East-North-Up (ENU) in meters, with the origin at the bounding-box
center and z=0 at ground level. For the small bounding boxes used here (a few
hundred meters to a couple of km) an equirectangular approximation about the
origin latitude is accurate to well under a meter, which is far below the
resolution that matters for ray tracing.
"""

from __future__ import annotations

import math

_EARTH_RADIUS_M = 6_378_137.0


class LocalProjection:
    """Convert between WGS84 (lat, lon) degrees and local ENU meters."""

    def __init__(self, origin_lat: float, origin_lon: float) -> None:
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self._lat0_rad = math.radians(origin_lat)
        self._cos_lat0 = math.cos(self._lat0_rad)

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        """(lat, lon) deg -> (east, north) meters relative to the origin."""
        d_lat = math.radians(lat - self.origin_lat)
        d_lon = math.radians(lon - self.origin_lon)
        east = _EARTH_RADIUS_M * d_lon * self._cos_lat0
        north = _EARTH_RADIUS_M * d_lat
        return east, north

    def to_latlon(self, east: float, north: float) -> tuple[float, float]:
        """(east, north) meters -> (lat, lon) deg."""
        d_lat = north / _EARTH_RADIUS_M
        d_lon = east / (_EARTH_RADIUS_M * self._cos_lat0)
        lat = self.origin_lat + math.degrees(d_lat)
        lon = self.origin_lon + math.degrees(d_lon)
        return lat, lon
