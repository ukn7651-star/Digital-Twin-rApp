import numpy as np
import pytest

from dtrapp.config import KpiConfig
from dtrapp.kpi import compute_kpis
from dtrapp.kpi.sinr import (
    associate_cells,
    compute_received_power_dbm,
    compute_sinr_db,
    thermal_noise_dbm,
)
from dtrapp.kpi.throughput import shannon_throughput, spectral_efficiency
from dtrapp.network.models import Cell, NetworkSnapshot, UE


def test_thermal_noise_known_value():
    # -174 dBm/Hz + 10log10(B) at T=290K, NF=0.
    n = thermal_noise_dbm(1.0, 0.0, 290.0)
    assert float(n) == pytest.approx(-173.98, abs=0.1)
    n20 = thermal_noise_dbm(20e6, 7.0, 290.0)
    assert float(n20) == pytest.approx(-173.98 + 10 * np.log10(20e6) + 7.0, abs=0.1)


def test_received_power_and_association():
    pg = np.array([[-80.0, -90.0], [-100.0, -85.0]])
    tx = np.array([46.0, 46.0])
    rx = compute_received_power_dbm(pg, tx)
    assert rx[0, 0] == pytest.approx(-34.0)
    serving, covered = associate_cells(rx, min_rx_power_dbm=-140.0)
    assert list(serving) == [0, 1]
    assert covered.all()


def test_association_coverage_threshold():
    rx = np.array([[-150.0, -160.0]])
    serving, covered = associate_cells(rx, min_rx_power_dbm=-140.0)
    assert serving[0] == 0
    assert not covered[0]


def test_sinr_monotonic_with_signal():
    # Stronger serving signal -> higher SINR.
    rx_weak = np.array([[-80.0, -90.0]])
    rx_strong = np.array([[-70.0, -90.0]])
    noise = thermal_noise_dbm(20e6, 7.0)
    s_weak = compute_sinr_db(rx_weak, np.array([0]), noise)
    s_strong = compute_sinr_db(rx_strong, np.array([0]), noise)
    assert s_strong[0] > s_weak[0]


def test_spectral_efficiency_cap():
    se = spectral_efficiency(np.array([0.0]), se_cap=100.0)
    assert se[0] == pytest.approx(1.0)  # log2(1+1)
    capped = spectral_efficiency(np.array([100.0]), se_cap=7.0)
    assert capped[0] == pytest.approx(7.0)


def test_resource_sharing_splits_bandwidth():
    # Two UEs on cell 0, one on cell 1; equal SINR.
    sinr = np.array([0.0, 0.0, 0.0])  # SINR=1 -> SE=1
    serving = np.array([0, 0, 1])
    bw = np.array([20e6, 20e6])
    ue_mbps, cell_mbps = shannon_throughput(sinr, serving, bw, num_cells=2)
    # Cell 0 split between two UEs -> each 10 MHz * 1 b/s/Hz = 10 Mbps.
    assert ue_mbps[0] == pytest.approx(10.0)
    assert ue_mbps[1] == pytest.approx(10.0)
    # UE alone on cell 1 -> full 20 MHz = 20 Mbps.
    assert ue_mbps[2] == pytest.approx(20.0)
    assert cell_mbps[0] == pytest.approx(20.0)
    assert cell_mbps[1] == pytest.approx(20.0)


def test_uncovered_ue_zero_throughput():
    sinr = np.array([0.0, 0.0])
    serving = np.array([0, 0])
    bw = np.array([20e6])
    covered = np.array([True, False])
    ue_mbps, cell_mbps = shannon_throughput(sinr, serving, bw, 1, covered=covered)
    assert ue_mbps[1] == 0.0
    # Covered UE gets full bandwidth (uncovered not counted in sharing).
    assert ue_mbps[0] == pytest.approx(20.0)


def _toy_snapshot():
    cells = [
        Cell("c0", 0, 0, (0, 0, 25), 0, 8, 46, 3.5e9, 20e6),
        Cell("c1", 1, 0, (500, 0, 25), 0, 8, 46, 3.5e9, 20e6),
    ]
    ues = [
        UE("ue0", (10, 0, 1.5), 50, 7),
        UE("ue1", (490, 0, 1.5), 50, 7),
    ]
    return NetworkSnapshot(0, cells, ues)


def test_compute_kpis_end_to_end():
    snap = _toy_snapshot()
    # ue0 close to c0, ue1 close to c1.
    pg = np.array([[-70.0, -120.0], [-120.0, -70.0]])
    result = compute_kpis(snap, pg, KpiConfig())
    assert len(result.ues) == 2
    assert len(result.cells) == 2
    assert result.ues[0].serving_cell == "c0"
    assert result.ues[1].serving_cell == "c1"
    assert all(u.throughput_mbps > 0 for u in result.ues)


def test_compute_kpis_shape_mismatch_raises():
    snap = _toy_snapshot()
    with pytest.raises(ValueError):
        compute_kpis(snap, np.zeros((2, 3)), KpiConfig())
