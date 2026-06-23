"""Output writers: per-UE & per-cell throughput to CSV and JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from dtrapp.config import SimulationConfig
from dtrapp.kpi.results import SnapshotKpi

_UE_FIELDS = ["snapshot", "ue_id", "serving_cell", "x", "y", "sinr_db", "throughput_mbps"]
_CELL_FIELDS = ["snapshot", "cell_id", "num_attached", "throughput_mbps"]


def write_outputs(results: list[SnapshotKpi], config: SimulationConfig) -> list[Path]:
    """Write ue/cell CSVs and a combined JSON; return their paths."""
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ue_csv = _write_csv(out / "ue_throughput.csv", _UE_FIELDS, results, lambda s: s.ue_rows())
    cell_csv = _write_csv(
        out / "cell_throughput.csv", _CELL_FIELDS, results, lambda s: s.cell_rows()
    )

    json_path = out / "throughput.json"
    json_path.write_text(
        json.dumps(
            {"num_snapshots": len(results), "snapshots": [s.to_dict() for s in results]},
            indent=2,
        )
    )
    return [ue_csv, cell_csv, json_path]


def _write_csv(path: Path, fields, results, rows_of) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for snap in results:
            writer.writerows(rows_of(snap))
    return path
