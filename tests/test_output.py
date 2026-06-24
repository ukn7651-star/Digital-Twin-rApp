import csv
import json

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi
from dtrapp.runner.output import write_outputs


def _result():
    result = KpiResult()
    result.ues.append(UEKpi("ue0", "c0", 1.0, 2.0, 12.3, 80.0))
    result.cells.append(CellKpi("c0", 1, 80.0))
    return result


def test_write_csv_and_json(tmp_path):
    cfg = SimulationConfig(bbox=BoundingBox(52.0, 13.0, 52.01, 13.01), output_dir=str(tmp_path))
    written = write_outputs(_result(), cfg)
    names = {p.name for p in written}
    assert names == {"ue_throughput.csv", "cell_throughput.csv", "throughput.json"}

    with open(tmp_path / "ue_throughput.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["ue_id"] == "ue0"
    assert float(rows[0]["throughput_mbps"]) == 80.0

    payload = json.loads((tmp_path / "throughput.json").read_text())
    assert payload["ues"][0]["serving_cell"] == "c0"
    assert payload["cells"][0]["cell_id"] == "c0"
