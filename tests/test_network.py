from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.network import RandomNetworkSource

EXTENT = (-200.0, -200.0, 200.0, 200.0)


def _cfg(**kw):
    return SimulationConfig(bbox=BoundingBox(52.0, 13.0, 52.01, 13.01), **kw)


def test_cell_and_ue_counts():
    src = RandomNetworkSource(_cfg(num_sites=3, sectors_per_site=3, num_ues=25, seed=1), EXTENT)
    net = src.generate()
    assert len(net.cells) == 9
    assert len(net.ues) == 25
    azimuths = sorted(round(c.azimuth_deg, 3) for c in net.cells[:3])
    assert len(set(azimuths)) == 3


def test_reproducible_with_seed():
    a = RandomNetworkSource(_cfg(seed=123, num_ues=10), EXTENT).generate()
    b = RandomNetworkSource(_cfg(seed=123, num_ues=10), EXTENT).generate()
    assert [u.position for u in a.ues] == [u.position for u in b.ues]
    assert [c.position for c in a.cells] == [c.position for c in b.cells]


def test_generate_is_stable():
    src = RandomNetworkSource(_cfg(seed=5), EXTENT)
    a, b = src.generate(), src.generate()
    assert [c.position for c in a.cells] == [c.position for c in b.cells]
    assert [u.position for u in a.ues] == [u.position for u in b.ues]
