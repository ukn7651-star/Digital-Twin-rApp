"""Extrude OSM building footprints into 3D triangle meshes (z-up, meters).

Coordinate convention matches Sionna RT: a local ENU frame where +z is up and
the origin is the bounding-box center. Each footprint becomes a closed prism
(walls + roof + floor). Walls dominate radio propagation; roofs/floors use fan
triangulation, which is exact for convex footprints and a minor approximation
for concave ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from dtrapp.geometry.overpass import Building
from dtrapp.geometry.projection import LocalProjection


@dataclass
class Mesh:
    """A triangle mesh: vertices (list of (x,y,z)) and faces (vertex-index triples)."""

    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]

    def bounds(self):
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _signed_area(ring_xy: list[tuple[float, float]]) -> float:
    """Shoelace signed area; positive => counter-clockwise winding."""
    area = 0.0
    n = len(ring_xy)
    for i in range(n):
        x0, y0 = ring_xy[i]
        x1, y1 = ring_xy[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return 0.5 * area


def extrude_building(building: Building, proj: LocalProjection) -> Mesh | None:
    """Turn one footprint into a closed prism mesh, or None if degenerate."""
    ring = [proj.to_local(lat, lon) for (lat, lon) in building.outline_latlon]
    if len(ring) < 3:
        return None

    # Ensure counter-clockwise so roof normals point up.
    if _signed_area(ring) < 0:
        ring = list(reversed(ring))

    n = len(ring)
    h = building.height_m
    vertices: list[tuple[float, float, float]] = []
    # Bottom vertices [0, n), top vertices [n, 2n).
    for x, y in ring:
        vertices.append((x, y, 0.0))
    for x, y in ring:
        vertices.append((x, y, h))

    faces: list[tuple[int, int, int]] = []

    # Walls: quad per edge -> two triangles, outward-facing.
    for i in range(n):
        j = (i + 1) % n
        b_i, b_j = i, j
        t_i, t_j = i + n, j + n
        faces.append((b_i, b_j, t_j))
        faces.append((b_i, t_j, t_i))

    # Roof (top, +z up) fan triangulation.
    for i in range(1, n - 1):
        faces.append((n, n + i, n + i + 1))

    # Floor (bottom, -z down) fan triangulation, reversed winding.
    for i in range(1, n - 1):
        faces.append((0, i + 1, i))

    return Mesh(vertices, faces)


def make_ground_plane(
    min_x: float, min_y: float, max_x: float, max_y: float, margin: float = 20.0
) -> Mesh:
    """A flat z=0 rectangle covering the scene extent (plus a margin)."""
    x0, y0 = min_x - margin, min_y - margin
    x1, y1 = max_x + margin, max_y + margin
    vertices = [
        (x0, y0, 0.0),
        (x1, y0, 0.0),
        (x1, y1, 0.0),
        (x0, y1, 0.0),
    ]
    faces = [(0, 1, 2), (0, 2, 3)]
    return Mesh(vertices, faces)


def write_ply(mesh: Mesh, path) -> None:
    """Write an ASCII PLY triangle mesh (deterministic, human-readable)."""
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(mesh.vertices)}",
        "property float x",
        "property float y",
        "property float z",
        f"element face {len(mesh.faces)}",
        "property list uchar int vertex_indices",
        "end_header",
    ]
    for x, y, z in mesh.vertices:
        lines.append(f"{x:.6f} {y:.6f} {z:.6f}")
    for a, b, c in mesh.faces:
        lines.append(f"3 {a} {b} {c}")
    with open(path, "w", encoding="ascii") as fh:
        fh.write("\n".join(lines))
        fh.write("\n")
