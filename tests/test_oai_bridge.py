"""Tests for the twin->OAI interference-floor bridge (pure NumPy, no OAI/Sionna)."""

import numpy as np

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.network.models import Cell, Network, UE
from dtrapp.oai_bridge import (
    per_ue_interference_floor,
    write_per_ue_noise_configs,
)


def _cfg(**kw):
    return SimulationConfig(bbox=BoundingBox(52.499, 13.399, 52.501, 13.401), **kw)


def _cfr(strengths):
    nU, nC = len(strengths), len(strengths[0])
    h = np.zeros((nU, 1, nC, 4, 2, 4), dtype=complex)
    for u in range(nU):
        for c in range(nC):
            h[u, :, c] = strengths[u][c]
    return h


def test_rise_grows_with_interferer_strength():
    cells = [
        Cell("c0", (0.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("c1", (100.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
    ]
    # u0: negligible interferer; u1: strong interferer (both served by c0).
    ues = [UE("u0", (0, 0, 1.5), 20.0, 7.0), UE("u1", (1, 0, 1.5), 20.0, 7.0)]
    net = Network(cells, ues)
    cfr = _cfr([[1e-3, 1e-9], [1e-3, 5e-4]])

    floors = per_ue_interference_floor(net, cfr, _cfg())
    by_id = {f.ue_id: f for f in floors}
    assert by_id["u0"].serving_cell == "c0" and by_id["u1"].serving_cell == "c0"
    # Negligible interferer -> ~0 dB rise; strong interferer -> clearly positive.
    assert by_id["u0"].rise_db < 0.5
    assert by_id["u1"].rise_db > by_id["u0"].rise_db + 3.0
    # Stronger interference => lower wideband SINR.
    assert by_id["u1"].wideband_sinr_db < by_id["u0"].wideband_sinr_db


def test_neighbor_load_scales_rise():
    cells = [
        Cell("c0", (0.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("c1", (100.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
    ]
    ues = [UE("u0", (1, 0, 1.5), 20.0, 7.0)]
    net = Network(cells, ues)
    cfr = _cfr([[1e-3, 5e-4]])

    full = per_ue_interference_floor(net, cfr, _cfg(neighbor_load=1.0))[0]
    idle = per_ue_interference_floor(net, cfr, _cfg(neighbor_load=0.0))[0]
    assert idle.rise_db < full.rise_db
    assert idle.rise_db < 1e-6  # no neighbour activity -> no rise


def test_write_per_ue_noise_configs(tmp_path):
    cells = [
        Cell("c0", (0.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("c1", (100.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
    ]
    ues = [UE("u0", (0, 0, 1.5), 20.0, 7.0), UE("u1", (1, 0, 1.5), 20.0, 7.0)]
    net = Network(cells, ues)
    cfr = _cfr([[1e-3, 1e-9], [1e-3, 5e-4]])
    floors = per_ue_interference_floor(net, cfr, _cfg())

    p = tmp_path / "chan.conf"
    text = write_per_ue_noise_configs(floors, p, baseline_noise_power_db=-50.0)
    assert p.exists()
    assert "rfsimu_channel_ue0" in text and "rfsimu_channel_ue1" in text
    assert "noise_power_dB" in text and "modellist_rfsimu_1" in text
    # ue1 (strong interferer) must get a higher noise_power_dB than ue0.
    import re
    npows = [float(m) for m in re.findall(r"noise_power_dB = ([-\d.]+)", text)]
    assert len(npows) == 2 and npows[1] > npows[0]
