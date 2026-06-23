"""Integration test for the Sionna RT engine.

Skipped automatically when Sionna RT is not installed, so the rest of the suite
runs anywhere. Builds a tiny scene from canned OSM (no network), then ray-traces
a cell -> two-UE link and checks basic physics.
"""

import numpy as np
import pytest

pytest.importorskip("sionna.rt")

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.geometry import build_scene
from dtrapp.network.models import Cell, NetworkSnapshot, UE
from dtrapp.propagation import SionnaPropagationEngine


def _canned_overpass():
    return {
        "elements": [
            {"type": "node", "id": 1, "lat": 52.5000, "lon": 13.4000},
            {"type": "node", "id": 2, "lat": 52.5000, "lon": 13.4004},
            {"type": "node", "id": 3, "lat": 52.5003, "lon": 13.4004},
            {"type": "node", "id": 4, "lat": 52.5003, "lon": 13.4000},
            {
                "type": "way",
                "id": 100,
                "nodes": [1, 2, 3, 4, 1],
                "tags": {"building": "yes", "height": "20"},
            },
        ]
    }


def test_sionna_path_gain_smoke(tmp_path):
    cfg = SimulationConfig(bbox=BoundingBox(52.4990, 13.3985, 52.5013, 13.4019), max_depth=2)
    artifacts = build_scene(cfg.bbox, tmp_path, cfg, overpass_json=_canned_overpass())

    cell = Cell("c0", (-60.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6)
    near = UE("near", (-40.0, 0.0, 1.5), 50.0, 7.0)
    far = UE("far", (80.0, 0.0, 1.5), 50.0, 7.0)
    snap = NetworkSnapshot(0, [cell], [near, far])

    engine = SionnaPropagationEngine(artifacts.scene_xml, cfg)
    gain = engine.compute_path_gain(snap)

    assert gain.shape == (2, 1)
    assert np.all(np.isfinite(gain))
    assert gain[0, 0] > gain[1, 0]  # closer UE has higher path gain
