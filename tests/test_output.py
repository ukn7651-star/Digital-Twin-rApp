import csv
import json

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.kpi.results import CellKpi, SnapshotKpi, UEKpi
from dtrapp.runner.output import write_outputs


def _results():
    snap = SnapshotKpi(index=0)
    snap.ues.append(UEKpi(0, "ue0", "c0", 1.0, 2.0, 12.3, 80.0))
    snap.cells.append(CellKpi(0, "c0", 1, 80.0))
    return [snap]


def test_write_csv_and_json(tmp_path):
    cfg = SimulationConfig(bbox=BoundingBox(52.0, 13.0, 52.01, 13.01), output_dir=str(tmp_path))
    written = write_outputs(_results(), cfg)
    names = {p.name for p in written}
    assert names == {"ue_throughput.csv", "cell_throughput.csv", "throughput.json"}

    with open(tmp_path / "ue_throughput.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["ue_id"] == "ue0"
    assert float(rows[0]["throughput_mbps"]) == 80.0

    payload = json.loads((tmp_path / "throughput.json").read_text())
    assert payload["num_snapshots"] == 1
    assert payload["snapshots"][0]["ues"][0]["serving_cell"] == "c0"
