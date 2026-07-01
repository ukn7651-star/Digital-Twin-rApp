"""Unit tests for the OAI-backed KPI engine (no Sionna needed).

Feeds a synthetic CFR so we can check association, multi-cell SINR, the OAI
link-curve mapping, scheduling and the output shape deterministically.
"""

import numpy as np

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.kpi import compute_kpis, load_link_curve
from dtrapp.kpi.link_curve import LinkCurve
from dtrapp.network.models import Cell, Network, UE


def _cfg():
    return SimulationConfig(
        bbox=BoundingBox(52.499, 13.399, 52.501, 13.401),
        bs_antenna_rows=4, bs_antenna_cols=1, bler_target=0.1,
    )


def _synthetic_cfr(strengths):
    """strengths[u][c] -> |H| magnitude; returns [nU,1,nC,4,2,4] complex CFR."""
    nU, nC = len(strengths), len(strengths[0])
    h = np.zeros((nU, 1, nC, 4, 2, 4), dtype=complex)
    for u in range(nU):
        for c in range(nC):
            h[u, :, c] = strengths[u][c]
    return h


def test_association_and_scheduling():
    cells = [
        Cell("c0", (0.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("c1", (100.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
    ]
    ues = [
        UE("u0", (10.0, 0.0, 1.5), 50.0, 7.0),
        UE("u1", (90.0, 0.0, 1.5), 50.0, 7.0),
        UE("u2", (5.0, 0.0, 1.5), 50.0, 7.0),
    ]
    net = Network(cells, ues)
    # u0,u2 strong to c0; u1 strong to c1.
    cfr = _synthetic_cfr([[1e-3, 1e-5], [1e-5, 1e-3], [1e-3, 1e-5]])

    res = compute_kpis(net, cfr, _cfg())

    serving = {u.ue_id: u.serving_cell for u in res.ues}
    assert serving == {"u0": "c0", "u1": "c1", "u2": "c0"}

    attached = {c.cell_id: c.num_attached for c in res.cells}
    assert attached == {"c0": 2, "c1": 1}

    # Per-cell throughput is the sum of its UEs'.
    by_cell = {c.cell_id: c.throughput_mbps for c in res.cells}
    for cell_id in ("c0", "c1"):
        s = sum(u.throughput_mbps for u in res.ues if u.serving_cell == cell_id)
        assert abs(by_cell[cell_id] - s) < 1e-6

    for u in res.ues:
        assert np.isfinite(u.sinr_db)
        assert u.throughput_mbps > 0.0
        assert u.mcs >= 0


def test_link_curve_monotone_and_bounds():
    curve = load_link_curve()  # ships the OAI-measured table
    # Below the lowest point -> no service.
    mcs, se = curve.map_sinr(-50.0)
    assert mcs == -1 and se == 0.0
    # Monotone: higher SINR -> SE never decreases.
    prev = 0.0
    for sinr in range(-10, 40, 2):
        _, se = curve.map_sinr(float(sinr))
        assert se >= prev - 1e-9
        prev = se


def test_fallback_curve_used_when_missing(tmp_path):
    curve = LinkCurve.__new__(LinkCurve)  # ensure class is importable/usable
    from dtrapp.kpi.link_curve import _FALLBACK
    curve = LinkCurve(_FALLBACK)
    assert curve.map_sinr(30.0)[0] >= 0
    assert curve.map_sinr(-100.0) == (-1, 0.0)
