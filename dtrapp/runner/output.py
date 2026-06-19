"""Output writers: per-UE & per-cell throughput to CSV/JSON, optional heatmap."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from dtrapp.config import RunnerConfig
from dtrapp.kpi.results import SnapshotKpi

_UE_FIELDS = [
    "snapshot",
    "ue_id",
    "serving_cell",
    "x",
    "y",
    "z",
    "sinr_db",
    "spectral_efficiency",
    "throughput_mbps",
    "traffic_demand_mbps",
    "covered",
]
_CELL_FIELDS = [
    "snapshot",
    "cell_id",
    "num_attached",
    "throughput_mbps",
    "x",
    "y",
    "z",
]


def write_outputs(
    results: list[SnapshotKpi],
    config: RunnerConfig,
) -> list[Path]:
    """Write the configured output artifacts and return their paths."""
    out = Path(config.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if config.write_csv:
        written.append(_write_ue_csv(results, out / "ue_throughput.csv"))
        written.append(_write_cell_csv(results, out / "cell_throughput.csv"))

    if config.write_json:
        written.append(_write_json(results, out / "throughput.json"))

    if config.write_heatmap:
        path = _write_heatmaps(results, out)
        if path is not None:
            written.append(path)

    return written


def _write_ue_csv(results: list[SnapshotKpi], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_UE_FIELDS)
        writer.writeheader()
        for snap in results:
            for row in snap.ue_rows():
                writer.writerow(row)
    return path


def _write_cell_csv(results: list[SnapshotKpi], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CELL_FIELDS)
        writer.writeheader()
        for snap in results:
            for row in snap.cell_rows():
                writer.writerow(row)
    return path


def _write_json(results: list[SnapshotKpi], path: Path) -> Path:
    payload = {
        "num_snapshots": len(results),
        "snapshots": [snap.to_dict() for snap in results],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def _write_heatmaps(results: list[SnapshotKpi], out: Path) -> Path | None:
    """Scatter UE throughput over the scene with cell sites marked (snapshot 0)."""
    if not results:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # pragma: no cover
        return None

    snap = results[0]
    ue_x = [u.x for u in snap.ues]
    ue_y = [u.y for u in snap.ues]
    ue_t = [u.throughput_mbps for u in snap.ues]

    fig, ax = plt.subplots(figsize=(7, 6))
    sc = ax.scatter(ue_x, ue_y, c=ue_t, cmap="viridis", s=40, edgecolors="k")
    fig.colorbar(sc, ax=ax, label="UE throughput (Mbps)")
    ax.scatter(
        [c.x for c in snap.cells],
        [c.y for c in snap.cells],
        marker="^",
        c="red",
        s=120,
        label="cells",
    )
    ax.set_xlabel("East (m)")
    ax.set_ylabel("North (m)")
    ax.set_title(f"Downlink throughput - snapshot {snap.index}")
    ax.legend()
    ax.set_aspect("equal", adjustable="datalim")
    path = out / "heatmap_snapshot0.png"
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
