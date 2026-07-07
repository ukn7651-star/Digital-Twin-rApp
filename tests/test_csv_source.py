"""Tests for the real-site CSV network data source (no Sionna needed)."""

import math

import pytest

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.network import CsvNetworkSource


def _cfg(**kw):
    return SimulationConfig(bbox=BoundingBox(52.499, 13.399, 52.501, 13.401), **kw)


EXTENT = (-100.0, -100.0, 100.0, 100.0)


def test_cells_from_csv_with_sectorization(tmp_path):
    p = tmp_path / "cells.csv"
    p.write_text(
        "lat,lon,cell_id,height_m,sectors\n"
        "52.5,13.4,siteA,30.0,3\n"        # bbox centre -> (0,0), 3 sectors
        "52.5005,13.4,siteB,25.0,1\n"     # north of centre, single sector
        "40.0,10.0,far,10.0,3\n"          # outside bbox -> skipped
    )
    src = CsvNetworkSource(_cfg(cells_csv=str(p)), EXTENT)
    net = src.generate()

    assert len(net.cells) == 4  # 3 sectors + 1
    assert src.num_skipped == 1
    a0 = [c for c in net.cells if c.cell_id.startswith("siteA")]
    assert {c.azimuth_deg for c in a0} == {0.0, 120.0, 240.0}
    assert a0[0].position[0] == pytest.approx(0.0, abs=1e-6)
    assert a0[0].position[1] == pytest.approx(0.0, abs=1e-6)
    assert a0[0].position[2] == 30.0

    b = next(c for c in net.cells if c.cell_id.startswith("siteB"))
    # 0.0005 deg north ~= 55.7 m; east offset ~= 0.
    assert b.position[1] == pytest.approx(0.0005 * math.pi / 180 * 6_378_137.0, rel=1e-3)
    assert abs(b.position[0]) < 1e-6

    # UEs not given -> random UEs still generated over the real cells.
    assert len(net.ues) == _cfg().num_ues


def test_explicit_azimuth_and_ues_csv(tmp_path):
    cells = tmp_path / "cells.csv"
    cells.write_text("lat,lon,cell_id,azimuth_deg,tx_power_dbm\n52.5,13.4,c0,45.0,40.0\n")
    ues = tmp_path / "ues.csv"
    ues.write_text("lat,lon,ue_id\n52.5001,13.4001,alice\n52.4999,13.3999,bob\n")

    cfg = _cfg(cells_csv=str(cells), ues_csv=str(ues))
    net = CsvNetworkSource(cfg, EXTENT).generate()

    assert [c.cell_id for c in net.cells] == ["c0"]
    assert net.cells[0].azimuth_deg == 45.0
    assert net.cells[0].tx_power_dbm == 40.0
    assert [u.ue_id for u in net.ues] == ["alice", "bob"]
    assert net.ues[0].noise_figure_db == cfg.ue_noise_figure_db


def test_no_cells_in_bbox_raises(tmp_path):
    p = tmp_path / "cells.csv"
    p.write_text("lat,lon\n0.0,0.0\n")
    with pytest.raises(ValueError, match="no cells inside"):
        CsvNetworkSource(_cfg(cells_csv=str(p)), EXTENT).generate()
