"""Output writers: per-UE & per-cell throughput to CSV and JSON."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from dtrapp.config import SimulationConfig
from dtrapp.kpi.results import KpiResult

_UE_FIELDS = ["ue_id", "serving_cell", "x", "y", "sinr_db", "mcs", "throughput_mbps"]
_CELL_FIELDS = ["cell_id", "num_attached", "throughput_mbps"]


def write_outputs(result: KpiResult, config: SimulationConfig) -> list[Path]:
    """Write ue/cell CSVs and a combined JSON; return their paths."""
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ue_csv = _write_csv(out / "ue_throughput.csv", _UE_FIELDS, result.ue_rows())
    cell_csv = _write_csv(out / "cell_throughput.csv", _CELL_FIELDS, result.cell_rows())

    json_path = out / "throughput.json"
    json_path.write_text(json.dumps(result.to_dict(), indent=2))
    return [ue_csv, cell_csv, json_path]


def _write_csv(path: Path, fields, rows) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path
