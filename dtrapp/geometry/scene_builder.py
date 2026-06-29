"""Stage 1 orchestration: bounding box -> OSM -> Mitsuba scene.xml.

Single source of truth for the 3D world. If OSM cannot be fetched or parsed, or
yields no buildings, this raises `SceneBuildError` and stops. There is no
fallback geometry: silently substituting a different scene would produce
throughput numbers for the wrong world.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

from dtrapp.config import BoundingBox, GeometryConfig
from dtrapp.geometry import overpass as _ov
from dtrapp.geometry.extrude import (
    Mesh,
    extrude_building,
    make_ground_plane,
    write_ply,
)
from dtrapp.geometry.projection import LocalProjection

_MITSUBA_VERSION = "2.1.0"


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
    config: GeometryConfig | None = None,
    overpass_json: dict | None = None,
) -> SceneArtifacts:
    """Build a Mitsuba scene from OSM buildings within `bbox`.

    Parameters
    ----------
    bbox: geographic area to model.
    output_dir: directory to write scene.xml and meshes/ into.
    config: geometry parameters (defaults applied if None).
    overpass_json: optional pre-fetched Overpass payload. When provided the
        network is not contacted - used for testing and reproducible builds.
    """
    config = config or GeometryConfig()
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

    origin_lat, origin_lon = bbox.center
    proj = LocalProjection(origin_lat, origin_lon)

    shapes: list[tuple[str, str, str]] = []  # (shape_id, ply_relpath, material)
    all_bounds_x: list[float] = []
    all_bounds_y: list[float] = []

    for b in buildings:
        mesh = extrude_building(b, proj)
        if mesh is None:
            continue
        (mnx, mny, _), (mxx, mxy, _) = mesh.bounds()
        all_bounds_x += [mnx, mxx]
        all_bounds_y += [mny, mxy]
        shape_id = f"bldg-{b.osm_id}"
        rel = f"meshes/{shape_id}.ply"
        write_ply(mesh, out / rel)
        shapes.append((shape_id, rel, config.building_material))

    if not shapes:
        raise SceneBuildError(
            "All OSM building footprints were degenerate; no geometry produced."
        )

    extent = (min(all_bounds_x), min(all_bounds_y), max(all_bounds_x), max(all_bounds_y))

    ground = make_ground_plane(*extent)
    write_ply(ground, mesh_dir / "ground.ply")
    shapes.append(("ground", "meshes/ground.ply", config.ground_material))

    scene_xml = out / "scene.xml"
    _write_scene_xml(scene_xml, shapes)

    return SceneArtifacts(
        scene_xml=scene_xml,
        projection=proj,
        num_buildings=len(buildings),
        extent_m=extent,
    )


def _write_scene_xml(path: Path, shapes: list[tuple[str, str, str]]) -> None:
    """Write a Mitsuba 3 / Sionna RT compatible scene.xml.

    Radio materials follow Sionna's convention: a BSDF whose id is
    ``mat-<radio_material_name>`` (e.g. ``mat-itu_concrete``) is mapped by
    Sionna RT to the corresponding built-in RadioMaterial on load.
    """
    materials = sorted({m for (_, _, m) in shapes})
    lines = [f'<scene version="{_MITSUBA_VERSION}">']

    for mat in materials:
        bsdf_id = f"mat-{mat}"
        lines += [
            f'  <bsdf type="twosided" id={quoteattr(bsdf_id)}>',
            '    <bsdf type="diffuse">',
            '      <rgb value="0.6 0.6 0.6" name="reflectance"/>',
            "    </bsdf>",
            "  </bsdf>",
        ]

    for shape_id, rel, mat in shapes:
        bsdf_id = f"mat-{mat}"
        lines += [
            f'  <shape type="ply" id={quoteattr(shape_id)}>',
            f'    <string name="filename" value={quoteattr(rel)}/>',
            '    <boolean name="face_normals" value="true"/>',
            f'    <ref id={quoteattr(bsdf_id)} name="bsdf"/>',
            "  </shape>",
        ]

    lines.append("</scene>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
