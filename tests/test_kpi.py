"""KPI tests for the Sionna SYS link-level chain.

The KPI stage needs the ray-traced channel (CFR) plus Sionna SYS, so these tests
build a tiny scene from canned OSM (no network) and are skipped automatically
when Sionna is not installed.
"""

import numpy as np
import pytest

pytest.importorskip("sionna.rt")
pytest.importorskip("sionna.sys")

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.geometry import build_scene
from dtrapp.kpi import compute_kpis
from dtrapp.network.models import Cell, Network, UE
from dtrapp.propagation import SionnaPropagationEngine


def _canned_overpass():
    return {
        "elements": [
            {"type": "node", "id": 1, "lat": 52.5000, "lon": 13.4000},
            {"type": "node", "id": 2, "lat": 52.5000, "lon": 13.4006},
            {"type": "node", "id": 3, "lat": 52.5004, "lon": 13.4006},
            {"type": "node", "id": 4, "lat": 52.5004, "lon": 13.4000},
            {"type": "way", "id": 100, "nodes": [1, 2, 3, 4, 1],
             "tags": {"building": "yes", "height": "20"}},
        ]
    }


def _scene_and_engine(tmp_path):
    cfg = SimulationConfig(
        bbox=BoundingBox(52.4990, 13.3990, 52.5014, 13.4016),
        max_depth=2, carrier_freq_hz=3.5e9, bandwidth_hz=20e6,
        num_subcarriers=64, num_ofdm_symbols=8,
    )
    artifacts = build_scene(cfg.bbox, tmp_path, cfg, overpass_json=_canned_overpass())
    return cfg, SionnaPropagationEngine(artifacts.scene_xml, cfg)


def test_link_level_kpis_end_to_end(tmp_path):
    cfg, engine = _scene_and_engine(tmp_path)
    cells = [
        Cell("s0-c0", (-50.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("s1-c0", (60.0, 20.0, 25.0), 180.0, 46.0, 3.5e9, 20e6),
    ]
    ues = [
        UE("ue0", (-30.0, 0.0, 1.5), 50.0, 7.0),
        UE("ue1", (40.0, 10.0, 1.5), 50.0, 7.0),
        UE("ue2", (55.0, 18.0, 1.5), 50.0, 7.0),
    ]
    net = Network(cells, ues)

    cfr = engine.compute_cfr(net)
    assert cfr.shape[0] == len(ues)      # num_rx = UEs
    assert cfr.shape[2] == len(cells)    # num_tx = cells

    result = compute_kpis(net, cfr, cfg)
    assert len(result.ues) == 3
    assert len(result.cells) == 2

    # Every UE attaches to a real cell and gets non-negative, finite throughput.
    cell_ids = {c.cell_id for c in cells}
    for u in result.ues:
        assert u.serving_cell in cell_ids
        assert np.isfinite(u.throughput_mbps) and u.throughput_mbps >= 0.0

    # Throughput is capped by the 64QAM MCS table (table 1): max SE 5.5547 b/s/Hz.
    max_mbps = 20e6 * 5.5547 / 1e6
    assert all(u.throughput_mbps <= max_mbps + 1e-6 for u in result.ues)

    # Per-cell throughput equals the sum of its UEs' throughput.
    for c in result.cells:
        s = sum(u.throughput_mbps for u in result.ues if u.serving_cell == c.cell_id)
        assert c.throughput_mbps == pytest.approx(s, rel=1e-6)
        assert c.num_attached == sum(1 for u in result.ues if u.serving_cell == c.cell_id)


def test_resource_sharing_halves_throughput(tmp_path):
    # Two co-located UEs on the same cell should each get ~half of a lone UE's rate
    # (equal-airtime PF sharing), all else equal.
    cfg, engine = _scene_and_engine(tmp_path)
    cell = Cell("s0-c0", (-50.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6)
    far = Cell("s1-c0", (300.0, 300.0, 25.0), 0.0, 46.0, 3.5e9, 20e6)
    pos = (-30.0, 0.0, 1.5)

    solo = Network([cell, far], [UE("a", pos, 50.0, 7.0)])
    pair = Network([cell, far], [UE("a", pos, 50.0, 7.0), UE("b", pos, 50.0, 7.0)])

    r_solo = compute_kpis(solo, engine.compute_cfr(solo), cfg)
    r_pair = compute_kpis(pair, engine.compute_cfr(pair), cfg)

    t_solo = r_solo.ues[0].throughput_mbps
    assert all(u.serving_cell == "s0-c0" for u in r_pair.ues)
    for u in r_pair.ues:
        assert u.throughput_mbps == pytest.approx(0.5 * t_solo, rel=1e-3)
