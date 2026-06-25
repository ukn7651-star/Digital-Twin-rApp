import numpy as np
import pytest

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.kpi import compute_kpis
from dtrapp.kpi.sinr import (
    associate_cells,
    compute_received_power_dbm,
    compute_sinr_db,
    thermal_noise_dbm,
)
from dtrapp.network.models import Cell, Network, UE


def _cfg():
    return SimulationConfig(bbox=BoundingBox(52.0, 13.0, 52.01, 13.01))


def test_thermal_noise_known_value():
    assert float(thermal_noise_dbm(1.0, 0.0, 290.0)) == pytest.approx(-173.98, abs=0.1)
    n20 = thermal_noise_dbm(20e6, 7.0, 290.0)
    assert float(n20) == pytest.approx(-173.98 + 10 * np.log10(20e6) + 7.0, abs=0.1)


def test_received_power_and_association():
    rx = compute_received_power_dbm(
        np.array([[-80.0, -90.0], [-100.0, -85.0]]), np.array([46.0, 46.0])
    )
    assert rx[0, 0] == pytest.approx(-34.0)
    assert list(associate_cells(rx)) == [0, 1]


def test_sinr_monotonic_with_signal():
    noise = thermal_noise_dbm(20e6, 7.0)
    s_weak = compute_sinr_db(np.array([[-80.0, -90.0]]), np.array([0]), noise)
    s_strong = compute_sinr_db(np.array([[-70.0, -90.0]]), np.array([0]), noise)
    assert s_strong[0] > s_weak[0]


def _toy_network():
    cells = [
        Cell("c0", (0, 0, 25), 0, 46, 3.5e9, 20e6),
        Cell("c1", (500, 0, 25), 0, 46, 3.5e9, 20e6),
    ]
    ues = [UE("ue0", (10, 0, 1.5), 50, 7), UE("ue1", (490, 0, 1.5), 50, 7)]
    return Network(cells, ues)


def test_compute_kpis_shape_mismatch_raises():
    # The shape check happens before the throughput model, so this needs no Sionna.
    with pytest.raises(ValueError):
        compute_kpis(_toy_network(), np.zeros((2, 3)), _cfg())


def test_compute_kpis_end_to_end():
    # The throughput model uses Sionna SYS; skip if it is not installed.
    pytest.importorskip("sionna.sys")
    net = _toy_network()
    pg = np.array([[-70.0, -120.0], [-120.0, -70.0]])
    result = compute_kpis(net, pg, _cfg())
    assert len(result.ues) == 2
    assert len(result.cells) == 2
    assert result.ues[0].serving_cell == "c0"
    assert result.ues[1].serving_cell == "c1"
    assert all(u.throughput_mbps >= 0 for u in result.ues)
