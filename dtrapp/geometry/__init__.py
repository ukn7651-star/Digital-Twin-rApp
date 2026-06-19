"""Stage 1 - geometry: OSM bounding box -> 3D Mitsuba scene.

OpenStreetMap is the single source of the 3D environment. If OSM data cannot be
fetched or parsed for the requested area the builder raises and stops; there is
no fallback geometry by design.
"""

from dtrapp.geometry.projection import LocalProjection
from dtrapp.geometry.scene_builder import SceneBuildError, build_scene

__all__ = ["LocalProjection", "build_scene", "SceneBuildError"]
