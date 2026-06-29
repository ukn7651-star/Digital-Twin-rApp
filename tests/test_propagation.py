import numpy as np

from dtrapp.config import KpiConfig, PropagationConfig
from dtrapp.kpi import compute_kpis
from dtrapp.network.models import Cell, NetworkSnapshot, UE
from dtrapp.propagation import AnalyticalPropagationEngine, make_engine


def _snapshot(ue_positions):
    cell = Cell("c0", 0, 0, (0.0, 0.0, 25.0), 0.0, 0.0, 46.0, 3.5e9, 20e6)
    ues = [UE(f"ue{i}", p, 50.0, 7.0) for i, p in enumerate(ue_positions)]
    return NetworkSnapshot(0, [cell], ues)


def test_analytical_closer_ue_higher_gain():
    snap = _snapshot([(20.0, 0.0, 1.5), (200.0, 0.0, 1.5)])
    eng = AnalyticalPropagationEngine(config=PropagationConfig())
    gain = eng.compute_path_gain(snap)
    assert gain.shape == (2, 1)
    # Closer UE has higher (less negative) path gain.
    assert gain[0, 0] > gain[1, 0]


def test_analytical_boresight_alignment():
    # Cell boresight points +x (azimuth 0). UE in front gets more gain than behind.
    cell = Cell("c0", 0, 0, (0.0, 0.0, 25.0), 0.0, 0.0, 46.0, 3.5e9, 20e6)
    front = UE("front", (50.0, 0.0, 1.5), 50.0, 7.0)
    behind = UE("behind", (-50.0, 0.0, 1.5), 50.0, 7.0)
    snap = NetworkSnapshot(0, [cell], [front, behind])
    gain = AnalyticalPropagationEngine().compute_path_gain(snap)
    assert gain[0, 0] > gain[1, 0]


def test_sanity_closer_ue_higher_throughput():
    snap = _snapshot([(15.0, 0.0, 1.5), (150.0, 0.0, 1.5)])
    eng = AnalyticalPropagationEngine()
    gain = eng.compute_path_gain(snap)
    # Use a high SINR cap so the near/far difference is not clipped away in this
    # noise-limited single-cell sanity check.
    result = compute_kpis(snap, gain, KpiConfig(sinr_max_db=100.0, max_spectral_efficiency=1e3))
    near, far = result.ues[0], result.ues[1]
    assert near.sinr_db > far.sinr_db
    assert near.throughput_mbps > far.throughput_mbps


def test_make_engine_analytical():
    eng = make_engine("analytical", None, PropagationConfig())
    assert isinstance(eng, AnalyticalPropagationEngine)
