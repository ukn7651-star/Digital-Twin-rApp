import math

import pytest

from dtrapp.config import BoundingBox, GeometryConfig
from dtrapp.geometry import LocalProjection, build_scene
from dtrapp.geometry.extrude import _signed_area, extrude_building
from dtrapp.geometry.overpass import Building, OverpassError, parse_buildings
from dtrapp.geometry.scene_builder import SceneBuildError


def test_projection_roundtrip():
    proj = LocalProjection(52.5, 13.4)
    lat, lon = 52.5012, 13.4034
    e, n = proj.to_local(lat, lon)
    lat2, lon2 = proj.to_latlon(e, n)
    assert lat2 == pytest.approx(lat, abs=1e-7)
    assert lon2 == pytest.approx(lon, abs=1e-7)
    # Origin maps to (0, 0).
    assert proj.to_local(52.5, 13.4) == pytest.approx((0.0, 0.0))


def _square_overpass(height_tag=None):
    tags = {"building": "yes"}
    if height_tag is not None:
        tags["height"] = height_tag
    return {
        "elements": [
            {"type": "node", "id": 1, "lat": 52.5000, "lon": 13.4000},
            {"type": "node", "id": 2, "lat": 52.5000, "lon": 13.4002},
            {"type": "node", "id": 3, "lat": 52.5002, "lon": 13.4002},
            {"type": "node", "id": 4, "lat": 52.5002, "lon": 13.4000},
            {"type": "way", "id": 100, "nodes": [1, 2, 3, 4, 1], "tags": tags},
        ]
    }


def test_parse_buildings_height_from_tag():
    cfg = GeometryConfig(default_building_height=10.0)
    buildings = parse_buildings(_square_overpass("21"), cfg)
    assert len(buildings) == 1
    assert buildings[0].height_m == pytest.approx(21.0)
    assert len(buildings[0].outline_latlon) == 4  # closing node dropped


def test_parse_buildings_height_default():
    cfg = GeometryConfig(default_building_height=10.0)
    buildings = parse_buildings(_square_overpass(None), cfg)
    assert buildings[0].height_m == pytest.approx(10.0)


def test_parse_buildings_levels():
    cfg = GeometryConfig(default_building_height=10.0, meters_per_level=3.0)
    data = _square_overpass(None)
    data["elements"][-1]["tags"]["building:levels"] = "4"
    buildings = parse_buildings(data, cfg)
    assert buildings[0].height_m == pytest.approx(12.0)


def test_parse_buildings_no_elements_raises():
    with pytest.raises(OverpassError):
        parse_buildings({}, GeometryConfig())


def test_extrude_square_prism():
    proj = LocalProjection(52.5, 13.4)
    b = Building(
        outline_latlon=[
            (52.5000, 13.4000),
            (52.5000, 13.4002),
            (52.5002, 13.4002),
            (52.5002, 13.4000),
        ],
        height_m=10.0,
        osm_id=100,
    )
    mesh = extrude_building(b, proj)
    # 4 corners x 2 (bottom+top) = 8 vertices.
    assert len(mesh.vertices) == 8
    # walls: 4 edges x 2 tris = 8; roof 2; floor 2 => 12 faces.
    assert len(mesh.faces) == 12
    (_, _, minz), (_, _, maxz) = mesh.bounds()
    assert minz == pytest.approx(0.0)
    assert maxz == pytest.approx(10.0)


def test_signed_area_sign():
    ccw = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert _signed_area(ccw) > 0
    cw = list(reversed(ccw))
    assert _signed_area(cw) < 0


def test_build_scene_from_canned_json(tmp_path):
    bbox = BoundingBox(52.4999, 13.3999, 52.5003, 13.4003)
    artifacts = build_scene(
        bbox, tmp_path, GeometryConfig(), overpass_json=_square_overpass("12")
    )
    assert artifacts.scene_xml.exists()
    assert (tmp_path / "meshes" / "bldg-100.ply").exists()
    assert (tmp_path / "meshes" / "ground.ply").exists()
    assert artifacts.num_buildings == 1
    text = artifacts.scene_xml.read_text()
    assert "mat-itu_concrete" in text
    assert 'id="bldg-100"' in text


def test_build_scene_no_buildings_raises(tmp_path):
    bbox = BoundingBox(52.4999, 13.3999, 52.5003, 13.4003)
    with pytest.raises(SceneBuildError):
        build_scene(bbox, tmp_path, GeometryConfig(), overpass_json={"elements": []})
