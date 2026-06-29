import csv
import json

from dtrapp.config import RunnerConfig
from dtrapp.kpi.results import CellKpi, SnapshotKpi, UEKpi
from dtrapp.runner.output import write_outputs


def _results():
    snap = SnapshotKpi(index=0)
    snap.ues.append(
        UEKpi(0, "ue0", "c0", 1.0, 2.0, 1.5, 12.3, 4.0, 80.0, 50.0, True)
    )
    snap.cells.append(CellKpi(0, "c0", 1, 80.0, 0.0, 0.0, 25.0))
    return [snap]


def test_write_csv_and_json(tmp_path):
    cfg = RunnerConfig(
        output_dir=str(tmp_path),
        write_csv=True,
        write_json=True,
        write_heatmap=False,
    )
    written = write_outputs(_results(), cfg)
    names = {p.name for p in written}
    assert "ue_throughput.csv" in names
    assert "cell_throughput.csv" in names
    assert "throughput.json" in names

    with open(tmp_path / "ue_throughput.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["ue_id"] == "ue0"
    assert float(rows[0]["throughput_mbps"]) == 80.0

    payload = json.loads((tmp_path / "throughput.json").read_text())
    assert payload["num_snapshots"] == 1
    assert payload["snapshots"][0]["ues"][0]["serving_cell"] == "c0"


def test_write_heatmap(tmp_path):
    cfg = RunnerConfig(
        output_dir=str(tmp_path),
        write_csv=False,
        write_json=False,
        write_heatmap=True,
    )
    written = write_outputs(_results(), cfg)
    # Heatmap is optional (depends on matplotlib); if produced, it must exist.
    for p in written:
        assert p.exists()
