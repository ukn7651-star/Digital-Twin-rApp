"""Tests for the per-cell RT channel bridge and the per-(UE,cell) SINR helper.

Pure NumPy: no OAI, no Sionna. The live-stack behaviour these support is exercised
by experiments/multignb_null_control.py and experiments/multignb_fidelity_gap.py.
"""

import numpy as np
import pytest

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.kpi.engine import compute_kpis, per_ue_cell_sinr
from dtrapp.network.models import Cell, Network, UE
from oai.cfr_to_oai_multicell import (
    DEFAULT_TAPS,
    MODEL_FMT,
    per_cell_link_gains_db,
    write_multicell_taps,
    write_ue_conf,
)


def _cfg(**kw):
    return SimulationConfig(bbox=BoundingBox(52.499, 13.399, 52.501, 13.401), **kw)


def _network(n_ue=2):
    cells = [
        Cell("s0-c0", (0.0, 0.0, 25.0), 0.0, 46.0, 3.5e9, 20e6),
        Cell("s0-c1", (0.0, 0.0, 25.0), 180.0, 46.0, 3.5e9, 20e6),
    ]
    ues = [UE(f"ue{i}", (10.0 * (i + 1), 5.0, 1.5), 10.0, 7.0) for i in range(n_ue)]
    return Network(cells, ues)


def _cfr(strengths):
    """strengths[u][c] -> a flat channel of that amplitude on every antenna/RE."""
    nU, nC = len(strengths), len(strengths[0])
    h = np.zeros((nU, 1, nC, 4, 2, 4), dtype=complex)
    for u in range(nU):
        for c in range(nC):
            h[u, :, c] = strengths[u][c]
    return h


# --- per-cell link gains ---------------------------------------------------
def test_link_gains_anchor_best_cell_at_zero_db():
    cfr = _cfr([[1.0, 0.5], [0.25, 1.0]])
    g0 = per_cell_link_gains_db(cfr, 0, [0, 1])
    assert g0[0] == 0.0                       # ue0's best link is c0
    assert np.isclose(g0[1], 20 * np.log10(0.5), atol=1e-6)   # 6.02 dB down
    g1 = per_cell_link_gains_db(cfr, 1, [0, 1])
    assert g1[1] == 0.0                       # ue1's best link is c1
    assert np.isclose(g1[0], 20 * np.log10(0.25), atol=1e-6)


def test_gain_override_is_used_verbatim(tmp_path):
    cfr = _cfr([[1.0, 0.5]])
    diag = write_multicell_taps(tmp_path / "t.txt", cfr, 0, [0, 1],
                                gain_override_db=[0.0, -40.0])
    assert [m["gain_db"] for m in diag["models"]] == [0.0, -40.0]


def test_taps_file_matches_the_oai_patch_format(tmp_path):
    """One '<model> <ntaps> <path_loss_dB>' header per cell, then ntaps triplets."""
    cfr = _cfr([[1.0, 0.5]])
    out = tmp_path / "taps.txt"
    diag = write_multicell_taps(out, cfr, 0, [0, 1], num_taps=4)
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2 * (1 + 4)

    for k, off in enumerate((0, 5)):
        name, ntaps, pl = lines[off].split()
        assert name == MODEL_FMT.format(k=k)
        assert int(ntaps) == 4
        assert np.isclose(float(pl), diag["models"][k]["gain_db"], atol=1e-4)
        for t in range(1, 5):
            assert len(lines[off + t].split()) == 3   # delay_ns re im

    # DU-k connects k-th, so it reads model rfsimu_channel_ue{k}: cell order must hold.
    assert diag["rsrp_split_db"] > 0.0
    assert diag["best_cell_idx"] == 0


def test_default_is_a_single_tap(tmp_path):
    """The 3.84 MHz CFR export cannot resolve multipath; one tap carries the gain."""
    assert DEFAULT_TAPS == 1
    cfr = _cfr([[1.0, 0.5]])
    out = tmp_path / "taps.txt"
    diag = write_multicell_taps(out, cfr, 0, [0, 1])
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2 * (1 + 1)
    assert diag["num_taps"] == 1
    for off in (0, 2):
        assert int(lines[off].split()[1]) == 1
        assert float(lines[off + 1].split()[0]) == 0.0    # single tap sits at delay 0


def test_all_zero_channel_is_rejected(tmp_path):
    """A UE in outage has an all-zero CFR; unit-energy normalisation would inject silence.

    Without this guard the UE simply fails to sync, minutes later, with no indication
    that the taps file was the cause.
    """
    cfr = _cfr([[0.0, 0.0]])
    with pytest.raises(ValueError, match="all-zero ray-traced channel"):
        write_multicell_taps(tmp_path / "t.txt", cfr, 0, [0, 1])

    # A gain override does not rescue it: the patch normalises the *taps* by their energy.
    with pytest.raises(ValueError, match="all-zero ray-traced channel"):
        write_multicell_taps(tmp_path / "t2.txt", cfr, 0, [0, 1], gain_override_db=[0.0, -40.0])


def test_ue_conf_declares_one_channel_model_per_cell(tmp_path):
    conf = tmp_path / "ue.conf"
    write_ue_conf(conf, num_cells=2, noise_power_db=-17.5)
    text = conf.read_text()
    assert 'options = ("chanmod")' in text     # else the models are never instantiated
    assert 'model_name = "rfsimu_channel_ue0"' in text
    assert 'model_name = "rfsimu_channel_ue1"' in text
    # Identical noise on both cells: the only difference between them is the RT channel.
    assert text.count("noise_power_dB = -17.50") == 2


# --- per-(UE, cell) SINR ---------------------------------------------------
def test_per_ue_cell_sinr_matches_the_kpi_engine_on_the_serving_cell():
    """The controlled experiment must use the twin's own abstraction, not a copy of it."""
    net = _network(n_ue=3)
    cfr = _cfr([[1.0, 0.3], [0.2, 1.0], [0.7, 0.6]])
    cfg = _cfg(num_sites=1, sectors_per_site=2, num_ues=3)

    result = compute_kpis(net, cfr, cfg)
    eff = per_ue_cell_sinr(net, cfr, cfg)
    idx = {c.cell_id: i for i, c in enumerate(net.cells)}
    for u, ue in enumerate(result.ues):
        s = idx[ue.serving_cell]
        assert eff[u][s]["mcs"] == ue.mcs
        assert np.isclose(eff[u][s]["sinr_db"], ue.sinr_db, atol=1e-9)


def test_per_ue_cell_sinr_evaluates_the_non_serving_cell_too():
    net = _network(n_ue=1)
    cfr = _cfr([[1.0, 0.1]])                  # c0 is 20 dB stronger
    eff = per_ue_cell_sinr(net, cfr, _cfg(num_sites=1, sectors_per_site=2, num_ues=1))
    assert eff[0][0]["sinr_db"] > eff[0][1]["sinr_db"]
    assert eff[0][0]["se_bps_per_hz"] >= eff[0][1]["se_bps_per_hz"]


def test_neighbour_load_zero_raises_sinr():
    """The one-UE real stack has an idle neighbour; the twin must be evaluable there."""
    net = _network(n_ue=1)
    cfr = _cfr([[1.0, 0.8]])                  # strong interferer
    loaded = per_ue_cell_sinr(net, cfr, _cfg(num_sites=1, sectors_per_site=2,
                                             num_ues=1, neighbor_load=1.0))
    idle = per_ue_cell_sinr(net, cfr, _cfg(num_sites=1, sectors_per_site=2,
                                           num_ues=1, neighbor_load=0.0))
    assert idle[0][0]["sinr_db"] > loaded[0][0]["sinr_db"] + 3.0
