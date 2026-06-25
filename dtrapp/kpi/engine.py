"""High-level KPI engine: Network + path gains -> KpiResult (stages 4-5).

The path-gain matrix must be indexed [ue_index, cell_index] in the same order as
`network.ues` and `network.cells`.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi
from dtrapp.kpi.sinr import (
    associate_cells,
    compute_received_power_dbm,
    compute_sinr_db,
    thermal_noise_dbm,
)
from dtrapp.kpi.throughput import shannon_throughput
from dtrapp.network.models import Network


def compute_kpis(
    network: Network, path_gain_db: np.ndarray, config: SimulationConfig
) -> KpiResult:
    """Compute per-UE and per-cell KPIs for the network."""
    cells, ues = network.cells, network.ues
    num_ues, num_cells = len(ues), len(cells)

    path_gain_db = np.asarray(path_gain_db, dtype=float)
    if path_gain_db.shape != (num_ues, num_cells):
        raise ValueError(
            f"path_gain_db shape {path_gain_db.shape} != ({num_ues}, {num_cells})"
        )

    tx_power_dbm = np.array([c.tx_power_dbm for c in cells])
    bandwidth_hz = np.array([c.bandwidth_hz for c in cells])
    ue_nf_db = np.array([u.noise_figure_db for u in ues])

    rx_power_dbm = compute_received_power_dbm(path_gain_db, tx_power_dbm)
    serving = associate_cells(rx_power_dbm)
    noise_dbm = thermal_noise_dbm(bandwidth_hz[serving], ue_nf_db, config.temperature_k)
    sinr_db = compute_sinr_db(rx_power_dbm, serving, noise_dbm)
    ue_mbps, cell_mbps = shannon_throughput(sinr_db, serving, bandwidth_hz, num_cells)

    attached = np.bincount(serving, minlength=num_cells)

    result = KpiResult()
    for u, ue in enumerate(ues):
        result.ues.append(
            UEKpi(
                ue_id=ue.ue_id,
                serving_cell=cells[int(serving[u])].cell_id,
                x=ue.position[0],
                y=ue.position[1],
                sinr_db=float(sinr_db[u]),
                throughput_mbps=float(ue_mbps[u]),
            )
        )
    for c, cell in enumerate(cells):
        result.cells.append(
            CellKpi(
                cell_id=cell.cell_id,
                num_attached=int(attached[c]),
                throughput_mbps=float(cell_mbps[c]),
            )
        )
    return result
