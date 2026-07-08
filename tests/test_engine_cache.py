"""The channel cache and the EESM beta reuse must not change a single number.

Both are pure speedups for the coordinate ascent (which evaluates the KPI engine
hundreds of times on one ray-traced channel). If either ever changes a result, every
number in the paper moves silently, so they are pinned here.
"""

import numpy as np

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.kpi.engine import (
    EESM_BETA_BY_QM,
    ChannelCache,
    _eesm_eff_sinr_lin,
    _qm_for_mcs,
    _select_mcs_eesm,
    compute_kpis,
    per_ue_cell_sinr,
)
from dtrapp.kpi.link_curve import load_link_curve
from dtrapp.network.models import Cell, Network, UE


def _cfg(**kw):
    return SimulationConfig(bbox=BoundingBox(52.499, 13.399, 52.501, 13.401), **kw)


def _network(n_cells=3, n_ue=6):
    cells = [Cell(f"c{i}", (120.0 * i, 0.0, 25.0), 60.0 * i, 46.0, 3.5e9, 38.16e6)
             for i in range(n_cells)]
    ues = [UE(f"ue{i}", (30.0 * i, 20.0, 1.5), 10.0, 7.0) for i in range(n_ue)]
    return Network(cells, ues)


def _cfr(n_ue, n_cells, n_sc=64, seed=0):
    rng = np.random.default_rng(seed)
    shape = (n_ue, 1, n_cells, 4, 3, n_sc)
    h = (rng.normal(size=shape) + 1j * rng.normal(size=shape)) / np.sqrt(2)
    # geometric decay so cells are distinguishable and some UEs are cell-edge
    for u in range(n_ue):
        for c in range(n_cells):
            h[u, :, c] *= 10.0 ** (-(abs(u - 2 * c) + 1) / 4.0)
    return h


def test_channel_cache_changes_nothing():
    net = _network()
    cfr = _cfr(len(net.ues), len(net.cells))
    cfg = _cfg(num_sites=3, sectors_per_site=1, num_ues=len(net.ues), num_subcarriers=64)
    cache = ChannelCache(cfr)

    for cio in (None, np.array([0.0, 0.0, 0.0]), np.array([6.0, -3.0, 1.5])):
        a = compute_kpis(net, cfr, cfg, cio_db=cio)
        b = compute_kpis(net, cfr, cfg, cio_db=cio, cache=cache)
        assert [u.serving_cell for u in a.ues] == [u.serving_cell for u in b.ues]
        assert [u.mcs for u in a.ues] == [u.mcs for u in b.ues]
        for x, y in zip(a.ues, b.ues):
            assert x.sinr_db == y.sinr_db          # bit-exact, not approximately
            assert x.throughput_mbps == y.throughput_mbps
        assert [c.num_attached for c in a.cells] == [c.num_attached for c in b.cells]


def test_per_ue_cell_sinr_accepts_the_same_cache():
    net = _network()
    cfr = _cfr(len(net.ues), len(net.cells))
    cfg = _cfg(num_sites=3, sectors_per_site=1, num_ues=len(net.ues), num_subcarriers=64)
    a = per_ue_cell_sinr(net, cfr, cfg)
    b = per_ue_cell_sinr(net, cfr, cfg, cache=ChannelCache(cfr))
    assert a == b


def test_eesm_beta_reuse_matches_the_naive_per_candidate_loop():
    """The optimised selector evaluates one log-sum-exp per *modulation order*."""
    curve = load_link_curve()
    rng = np.random.default_rng(3)

    def naive(gamma_lin, table_index, beta_scale):
        for p in sorted(curve.points, key=lambda q: q["sinr_db"], reverse=True):
            beta = EESM_BETA_BY_QM[_qm_for_mcs(int(p["mcs"]), table_index)] * beta_scale
            eff = 10.0 * np.log10(max(_eesm_eff_sinr_lin(gamma_lin, beta), 1e-12))
            if eff >= p["sinr_db"]:
                return int(p["mcs"]), float(p["se_bps_per_hz"]), float(eff)
        beta = EESM_BETA_BY_QM[2] * beta_scale
        return -1, 0.0, float(10.0 * np.log10(max(_eesm_eff_sinr_lin(gamma_lin, beta), 1e-12)))

    for _ in range(40):
        # span outage through saturation
        gamma = 10.0 ** (rng.uniform(-1.5, 3.5)) * rng.gamma(2.0, 0.5, size=512)
        for scale in (1.0, 0.8):
            assert _select_mcs_eesm(curve, gamma, 1, scale) == naive(gamma, 1, scale)
