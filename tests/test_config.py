import pytest

from dtrapp.config import BoundingBox, SimulationConfig


def test_bbox_validation():
    with pytest.raises(ValueError):
        BoundingBox(1.0, 0.0, 0.0, 1.0)  # min_lat >= max_lat
    with pytest.raises(ValueError):
        BoundingBox(0.0, 1.0, 1.0, 0.0)  # min_lon >= max_lon


def test_bbox_center_and_overpass():
    bb = BoundingBox(52.0, 13.0, 52.02, 13.04)
    clat, clon = bb.center
    assert clat == pytest.approx(52.01)
    assert clon == pytest.approx(13.02)
    assert bb.as_overpass_bbox() == "52.0,13.0,52.02,13.04"


def test_config_yaml_roundtrip(tmp_path):
    cfg = SimulationConfig(bbox=BoundingBox(52.0, 13.0, 52.02, 13.04))
    cfg.network.seed = 7
    cfg.network.tx_antenna.num_rows = 8
    cfg.runner.num_snapshots = 5
    path = tmp_path / "c.yaml"
    cfg.to_yaml(path)

    loaded = SimulationConfig.from_yaml(path)
    assert loaded.network.seed == 7
    assert loaded.network.tx_antenna.num_rows == 8
    assert loaded.runner.num_snapshots == 5
    assert loaded.bbox.min_lat == 52.0


def test_config_requires_bbox():
    with pytest.raises(ValueError):
        SimulationConfig.from_dict({})
