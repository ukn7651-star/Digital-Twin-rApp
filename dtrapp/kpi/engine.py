"""High-level KPI engine: NetworkSnapshot + path gains -> SnapshotKpi.

Bridges the array-level SINR/throughput math to the network data model. The
path-gain matrix produced by the propagation stage must be indexed
[ue_index, cell_index] in the same order as `snapshot.ues` and `snapshot.cells`.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import KpiConfig
from dtrapp.kpi.results import CellKpi, SnapshotKpi, UEKpi
from dtrapp.kpi.sinr import (
    associate_cells,
    compute_received_power_dbm,
    compute_sinr_db,
    thermal_noise_dbm,
)
from dtrapp.kpi.throughput import shannon_throughput, spectral_efficiency
from dtrapp.network.models import NetworkSnapshot


def compute_kpis(
    snapshot: NetworkSnapshot,
    path_gain_db: np.ndarray,
    config: KpiConfig | None = None,
) -> SnapshotKpi:
    """Compute per-UE and per-cell KPIs for one snapshot.

    path_gain_db: (num_ues, num_cells) channel power gain in dB.
    """
    config = config or KpiConfig()
    cells = snapshot.cells
    ues = snapshot.ues
    num_ues = len(ues)
    num_cells = len(cells)

    path_gain_db = np.asarray(path_gain_db, dtype=float)
    if path_gain_db.shape != (num_ues, num_cells):
        raise ValueError(
            f"path_gain_db shape {path_gain_db.shape} != "
            f"(num_ues={num_ues}, num_cells={num_cells})"
        )

    tx_power_dbm = np.array([c.tx_power_dbm for c in cells], dtype=float)
    bandwidth_hz = np.array([c.bandwidth_hz for c in cells], dtype=float)
    ue_nf_db = np.array([u.noise_figure_db for u in ues], dtype=float)

    rx_power_dbm = compute_received_power_dbm(path_gain_db, tx_power_dbm)
    serving, covered = associate_cells(rx_power_dbm, config.min_rx_power_dbm)

    # Per-UE noise uses each UE's serving-cell bandwidth and its noise figure.
    serving_bw = bandwidth_hz[serving]
    noise_dbm = thermal_noise_dbm(serving_bw, ue_nf_db, config.temperature_k)

    sinr_db = compute_sinr_db(
        rx_power_dbm,
        serving,
        noise_dbm,
        sinr_min_db=config.sinr_min_db,
        sinr_max_db=config.sinr_max_db,
    )

    ue_mbps, cell_mbps = shannon_throughput(
        sinr_db,
        serving,
        bandwidth_hz,
        num_cells,
        covered=covered,
        se_cap=config.max_spectral_efficiency,
    )
    se = spectral_efficiency(sinr_db, config.max_spectral_efficiency)
    se = np.where(covered, se, 0.0)

    attached_counts = np.zeros(num_cells, dtype=int)
    for u in range(num_ues):
        if covered[u]:
            attached_counts[int(serving[u])] += 1

    result = SnapshotKpi(index=snapshot.index)
    for u in range(num_ues):
        ue = ues[u]
        result.ues.append(
            UEKpi(
                snapshot=snapshot.index,
                ue_id=ue.ue_id,
                serving_cell=cells[int(serving[u])].cell_id if covered[u] else "",
                x=ue.position[0],
                y=ue.position[1],
                z=ue.position[2],
                sinr_db=float(sinr_db[u]) if covered[u] else float("nan"),
                spectral_efficiency=float(se[u]),
                throughput_mbps=float(ue_mbps[u]),
                traffic_demand_mbps=ue.traffic_demand_mbps,
                covered=bool(covered[u]),
            )
        )

    for c in range(num_cells):
        cell = cells[c]
        result.cells.append(
            CellKpi(
                snapshot=snapshot.index,
                cell_id=cell.cell_id,
                num_attached=int(attached_counts[c]),
                throughput_mbps=float(cell_mbps[c]),
                x=cell.position[0],
                y=cell.position[1],
                z=cell.position[2],
            )
        )

    return result
