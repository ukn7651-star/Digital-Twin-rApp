import pytest

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.network import RandomNetworkSource

EXTENT = (-200.0, -200.0, 200.0, 200.0)


def _cfg(**kw):
    return SimulationConfig(bbox=BoundingBox(52.0, 13.0, 52.01, 13.01), **kw)


def test_cell_and_ue_counts():
    src = RandomNetworkSource(_cfg(num_sites=3, sectors_per_site=3, num_ues=25, seed=1), EXTENT)
    snap = src.snapshot(0)
    assert len(snap.cells) == 9
    assert len(snap.ues) == 25
    azimuths = sorted(round(c.azimuth_deg, 3) for c in snap.cells[:3])
    assert len(set(azimuths)) == 3


def test_reproducible_with_seed():
    a = RandomNetworkSource(_cfg(seed=123, num_ues=10), EXTENT).snapshot(0)
    b = RandomNetworkSource(_cfg(seed=123, num_ues=10), EXTENT).snapshot(0)
    assert [u.position for u in a.ues] == [u.position for u in b.ues]
    assert [c.position for c in a.cells] == [c.position for c in b.cells]


def test_static_cells_no_mobility():
    src = RandomNetworkSource(_cfg(seed=5, ue_mobility_m=0.0, num_snapshots=3), EXTENT)
    s0, s1 = src.snapshot(0), src.snapshot(1)
    assert [c.position for c in s0.cells] == [c.position for c in s1.cells]
    assert [u.position for u in s0.ues] == [u.position for u in s1.ues]


def test_mobility_moves_ues_within_radius():
    src = RandomNetworkSource(
        _cfg(seed=5, ue_mobility_m=10.0, num_ues=20, num_snapshots=2), EXTENT
    )
    s0, s1 = src.snapshot(0), src.snapshot(1)
    moved = False
    for a, b in zip(s0.ues, s1.ues):
        dist = ((a.position[0] - b.position[0]) ** 2 + (a.position[1] - b.position[1]) ** 2) ** 0.5
        assert dist <= 10.0 + 1e-6
        moved = moved or dist > 0
    assert moved


def test_index_out_of_range():
    with pytest.raises(IndexError):
        RandomNetworkSource(_cfg(num_snapshots=1), EXTENT).snapshot(5)
