"""Stage 1 orchestration: bounding box -> OSM -> Mitsuba scene.xml.

OpenStreetMap is the single source of the 3D world. If OSM cannot be fetched or
parsed, or yields no buildings, this raises `SceneBuildError` and stops. There
is no fallback geometry: substituting a different scene would produce throughput
numbers for the wrong world.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.geometry import overpass as _ov
from dtrapp.geometry.extrude import extrude_building, make_ground_plane, write_ply
from dtrapp.geometry.projection import LocalProjection


class SceneBuildError(RuntimeError):
    """Raised when the 3D scene cannot be built from OSM. No fallback follows."""


@dataclass
class SceneArtifacts:
    """Result of stage 1: the scene file plus metadata for later stages."""

    scene_xml: Path
    projection: LocalProjection
    num_buildings: int
    extent_m: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


def build_scene(
    bbox: BoundingBox,
    output_dir: str | Path,
    config: SimulationConfig,
    overpass_json: dict | None = None,
) -> SceneArtifacts:
    """Build a Mitsuba scene from OSM buildings within `bbox`.

    `overpass_json` lets callers pass a pre-fetched payload (used by tests) so
    the network is not contacted.
    """
    out = Path(output_dir)
    mesh_dir = out / "meshes"
    mesh_dir.mkdir(parents=True, exist_ok=True)

    if overpass_json is None:
        overpass_json = _ov.fetch_overpass_json(bbox, config)

    try:
        buildings = _ov.parse_buildings(overpass_json, config)
    except _ov.OverpassError as exc:
        raise SceneBuildError(str(exc)) from exc

    if not buildings:
        raise SceneBuildError(
            f"No OSM buildings found in bbox {bbox.as_overpass_bbox()}. "
            "Refusing to fabricate geometry (no fallback)."
        )

    proj = LocalProjection(*bbox.center)
    shapes: list[tuple[str, str]] = []  # (shape_id, ply_relpath)
    xs: list[float] = []
    ys: list[float] = []

    for b in buildings:
        mesh = extrude_building(b, proj)
        if mesh is None:
            continue
        (mnx, mny, _), (mxx, mxy, _) = mesh.bounds()
        xs += [mnx, mxx]
        ys += [mny, mxy]
        rel = f"meshes/bldg-{b.osm_id}.ply"
        write_ply(mesh, out / rel)
        shapes.append((f"bldg-{b.osm_id}", rel))

    if not shapes:
        raise SceneBuildError("All building footprints were degenerate.")

    extent = (min(xs), min(ys), max(xs), max(ys))
    write_ply(make_ground_plane(*extent), mesh_dir / "ground.ply")
    shapes.append(("ground", "meshes/ground.ply"))

    scene_xml = out / "scene.xml"
    _write_scene_xml(scene_xml, shapes, config.building_material)
    return SceneArtifacts(scene_xml, proj, len(buildings), extent)


def _write_scene_xml(path: Path, shapes: list[tuple[str, str]], material: str) -> None:
    """Write a Mitsuba 3 / Sionna RT scene.xml.

    Sionna maps a BSDF whose id is ``mat-<name>`` (e.g. ``mat-itu_concrete``) to
    the matching built-in RadioMaterial on load.
    """
    bsdf_id = f"mat-{material}"
    lines = [
        '<scene version="2.1.0">',
        f"  <bsdf type=\"twosided\" id={quoteattr(bsdf_id)}>",
        '    <bsdf type="diffuse">',
        '      <rgb value="0.6 0.6 0.6" name="reflectance"/>',
        "    </bsdf>",
        "  </bsdf>",
    ]
    for shape_id, rel in shapes:
        lines += [
            f"  <shape type=\"ply\" id={quoteattr(shape_id)}>",
            f"    <string name=\"filename\" value={quoteattr(rel)}/>",
            '    <boolean name="face_normals" value="true"/>',
            f"    <ref id={quoteattr(bsdf_id)} name=\"bsdf\"/>",
            "  </shape>",
        ]
    lines.append("</scene>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
