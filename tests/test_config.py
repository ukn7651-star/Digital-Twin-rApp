import pytest

from dtrapp.config import BoundingBox, SimulationConfig


def _cfg():
    return SimulationConfig(bbox=BoundingBox(52.0, 13.0, 52.02, 13.04))


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
    cfg = _cfg()
    cfg.seed = 7
    cfg.num_ues = 5
    path = tmp_path / "c.yaml"
    cfg.to_yaml(path)

    loaded = SimulationConfig.from_yaml(path)
    assert loaded.seed == 7
    assert loaded.num_ues == 5
    assert loaded.bbox.min_lat == 52.0


def test_config_requires_bbox():
    with pytest.raises(ValueError):
        SimulationConfig.from_dict({})


def test_config_coerces_scientific_notation_strings():
    # YAML parses unsigned scientific notation (e.g. "3.5e9") as a string;
    # from_dict must coerce numeric fields back to float/int.
    cfg = SimulationConfig.from_dict(
        {
            "bbox": {"min_lat": 52.0, "min_lon": 13.0, "max_lat": 52.02, "max_lon": 13.04},
            "carrier_freq_hz": "3.5e9",
            "bandwidth_hz": "20.0e6",
            "subcarrier_spacing_hz": "30.0e3",
            "num_subcarriers": "128",
        }
    )
    assert isinstance(cfg.carrier_freq_hz, float) and cfg.carrier_freq_hz == 3.5e9
    assert isinstance(cfg.bandwidth_hz, float) and cfg.bandwidth_hz == 20e6
    assert isinstance(cfg.subcarrier_spacing_hz, float) and cfg.subcarrier_spacing_hz == 30e3
    assert isinstance(cfg.num_subcarriers, int) and cfg.num_subcarriers == 128
