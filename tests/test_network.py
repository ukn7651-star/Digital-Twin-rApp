import pytest

from dtrapp.config import NetworkConfig
from dtrapp.network import RandomNetworkSource

EXTENT = (-200.0, -200.0, 200.0, 200.0)


def test_cell_and_ue_counts():
    cfg = NetworkConfig(num_sites=3, sectors_per_site=3, num_ues=25, seed=1)
    src = RandomNetworkSource(cfg, EXTENT, num_snapshots=2)
    snap = src.snapshot(0)
    assert len(snap.cells) == 9
    assert len(snap.ues) == 25
    # Sectors per site have distinct azimuths.
    site0 = [c for c in snap.cells if c.site_id == 0]
    azimuths = sorted(round(c.azimuth_deg, 3) for c in site0)
    assert len(set(azimuths)) == 3


def test_reproducible_with_seed():
    cfg = NetworkConfig(seed=123, num_ues=10)
    a = RandomNetworkSource(cfg, EXTENT).snapshot(0)
    b = RandomNetworkSource(NetworkConfig(seed=123, num_ues=10), EXTENT).snapshot(0)
    assert [u.position for u in a.ues] == [u.position for u in b.ues]
    assert [c.position for c in a.cells] == [c.position for c in b.cells]


def test_static_cells_across_snapshots():
    cfg = NetworkConfig(seed=5, ue_mobility_m=0.0)
    src = RandomNetworkSource(cfg, EXTENT, num_snapshots=3)
    s0, s1 = src.snapshot(0), src.snapshot(1)
    assert [c.position for c in s0.cells] == [c.position for c in s1.cells]
    # No mobility -> UE positions unchanged.
    assert [u.position for u in s0.ues] == [u.position for u in s1.ues]


def test_mobility_moves_ues_within_radius():
    cfg = NetworkConfig(seed=5, ue_mobility_m=10.0, num_ues=20)
    src = RandomNetworkSource(cfg, EXTENT, num_snapshots=2)
    s0, s1 = src.snapshot(0), src.snapshot(1)
    moved = False
    for a, b in zip(s0.ues, s1.ues):
        dist = ((a.position[0] - b.position[0]) ** 2 + (a.position[1] - b.position[1]) ** 2) ** 0.5
        assert dist <= 10.0 + 1e-6
        if dist > 0:
            moved = True
    assert moved


def test_index_out_of_range():
    src = RandomNetworkSource(NetworkConfig(), EXTENT, num_snapshots=1)
    with pytest.raises(IndexError):
        src.snapshot(5)
