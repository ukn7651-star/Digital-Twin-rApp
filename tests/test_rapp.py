"""Tests for the traffic-steering rApp closed loop (no Sionna needed).

A deterministic congested-cell scenario: several UEs pile onto one cell while a
neighbour sits idle. The rApp should steer cell-edge UEs to the idle cell,
raising proportional-fair utility and reducing the peak cell load.
"""

import numpy as np

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.kpi import compute_kpis
from dtrapp.rapp import kpi_metrics, run_traffic_steering
from dtrapp.network.models import Cell, Network, UE


def _cfg():
    return SimulationConfig(
        bbox=BoundingBox(52.499, 13.399, 52.501, 13.401),
        bs_antenna_rows=4, bs_antenna_cols=1, bler_target=0.1,
    )


def _cfr(strengths):
    """strengths[u][c] -> |H| magnitude; returns [nU,1,nC,4,2,4] complex CFR."""
    nU, nC = len(strengths), len(strengths[0])
    h = np.zeros((nU, 1, nC, 4, 2, 4), dtype=complex)
    for u in range(nU):
        for c in range(nC):
            h[u, :, c] = strengths[u][c]
    return h


def _congested_scenario():
    cells = [
        Cell("c0", (0.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("c1", (80.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
    ]
    # 4 UEs locked to c0 (strong), 2 cell-edge UEs marginally preferring c0.
    strengths = [
        [1e-3, 1e-7], [1e-3, 1e-7], [1e-3, 1e-7], [1e-3, 1e-7],
        [1.05e-4, 1.0e-4], [1.05e-4, 1.0e-4],
    ]
    ues = [UE(f"u{i}", (float(i), 0.0, 1.5), 20.0, 7.0) for i in range(6)]
    return Network(cells, ues), _cfr(strengths)


def test_baseline_is_congested():
    net, cfr = _congested_scenario()
    res = compute_kpis(net, cfr, _cfg())  # cio=None -> plain strongest-cell
    loads = {c.cell_id: c.num_attached for c in res.cells}
    assert loads == {"c0": 6, "c1": 0}  # everyone piles onto c0


def test_cio_biases_association():
    net, cfr = _congested_scenario()
    # A big positive CIO on c1 must pull the edge UEs (and only those) over.
    res = compute_kpis(net, cfr, _cfg(), cio_db=np.array([0.0, 3.0]))
    loads = {c.cell_id: c.num_attached for c in res.cells}
    assert loads == {"c0": 4, "c1": 2}


def test_traffic_steering_improves_utility_and_balances_load():
    net, cfr = _congested_scenario()
    out = run_traffic_steering(net, cfr, _cfg(), step_db=1.0)

    # Utility (sum-log throughput) strictly improves.
    assert out.steered_metrics["utility"] > out.baseline_metrics["utility"]
    # Peak cell load drops (congestion relieved).
    assert out.steered_metrics["max_load"] < out.baseline_metrics["max_load"]
    # Cell-edge (5th pct) throughput improves.
    assert out.steered_metrics["edge_mbps"] > out.baseline_metrics["edge_mbps"]
    # The idle cell c1 is made relatively more attractive than the congested c0
    # (CIO is relative, so the loop may raise c1 and/or lower c0).
    assert out.cio_db[1] - out.cio_db[0] > 0.0


def test_steering_history_utility_monotone():
    net, cfr = _congested_scenario()
    out = run_traffic_steering(net, cfr, _cfg(), step_db=1.0)
    utils = [h["utility"] for h in out.history]
    assert all(b >= a - 1e-9 for a, b in zip(utils, utils[1:]))  # non-decreasing


def test_gains_report_positive_edge():
    net, cfr = _congested_scenario()
    out = run_traffic_steering(net, cfr, _cfg(), step_db=1.0)
    gains = out.gains_pct()
    assert gains["edge_mbps"] > 0.0
    assert gains["max_load_delta"] < 0.0


def test_no_op_when_already_balanced():
    # Two well-separated cells, one UE each: nothing to steer.
    cells = [
        Cell("c0", (0.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("c1", (80.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
    ]
    ues = [UE("u0", (0.0, 0.0, 1.5), 20.0, 7.0), UE("u1", (80.0, 0.0, 1.5), 20.0, 7.0)]
    net = Network(cells, ues)
    cfr = _cfr([[1e-3, 1e-7], [1e-7, 1e-3]])
    out = run_traffic_steering(net, cfr, _cfg(), step_db=1.0)
    # Already balanced -> utility cannot improve; loads unchanged.
    assert out.steered_metrics["utility"] <= out.baseline_metrics["utility"] + 1e-6
    assert out.steered_metrics["max_load"] == out.baseline_metrics["max_load"]
