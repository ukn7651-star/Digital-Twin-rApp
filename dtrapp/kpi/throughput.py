"""SINR -> downlink throughput with per-cell resource sharing (stage 5).

v1 model:
  spectral efficiency  SE = min(log2(1 + SINR_lin), SE_cap)   [bit/s/Hz]
  resource sharing      each cell splits its time-frequency resources equally
                        among its attached UEs (equal share), so a UE alone on
                        a cell gets the full bandwidth.
  per-UE throughput     R_u = (B_cell / K_cell) * SE_u         [bit/s]
  per-cell throughput   R_cell = sum over attached UEs of R_u

This is the clean seam for future upgrades: replace `shannon_throughput` (and
the equal-share scheduler inside it) with 5G-NR MCS tables, MIMO layers, and a
proportional-fair / PRB scheduler without changing the SINR or runner layers.
"""

from __future__ import annotations

import numpy as np


def spectral_efficiency(sinr_db: np.ndarray, se_cap: float = np.inf) -> np.ndarray:
    """Shannon spectral efficiency (bit/s/Hz), optionally capped."""
    sinr_lin = 10.0 ** (np.asarray(sinr_db, dtype=float) / 10.0)
    se = np.log2(1.0 + sinr_lin)
    return np.minimum(se, se_cap)


def shannon_throughput(
    sinr_db: np.ndarray,
    serving: np.ndarray,
    bandwidth_hz: np.ndarray,
    num_cells: int,
    covered: np.ndarray | None = None,
    se_cap: float = np.inf,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute per-UE and per-cell downlink throughput in Mbps.

    Parameters
    ----------
    sinr_db: (num_ues,) SINR per UE in dB.
    serving: (num_ues,) serving cell index per UE.
    bandwidth_hz: (num_cells,) cell bandwidth.
    num_cells: total number of cells (for per-cell aggregation).
    covered: (num_ues,) bool; UEs with False get zero throughput.
    se_cap: spectral-efficiency cap in bit/s/Hz.

    Returns
    -------
    (ue_mbps, cell_mbps): per-UE (num_ues,) and per-cell (num_cells,) Mbps.
    """
    sinr_db = np.asarray(sinr_db, dtype=float)
    serving = np.asarray(serving)
    bandwidth_hz = np.asarray(bandwidth_hz, dtype=float)
    num_ues = sinr_db.shape[0]

    if covered is None:
        covered = np.ones(num_ues, dtype=bool)

    se = spectral_efficiency(sinr_db, se_cap)
    se = np.where(covered, se, 0.0)

    # Count attached (and covered) UEs per cell for equal-share resources.
    attached_per_cell = np.zeros(num_cells, dtype=float)
    for c in serving[covered]:
        attached_per_cell[c] += 1.0

    ue_mbps = np.zeros(num_ues, dtype=float)
    for u in range(num_ues):
        if not covered[u]:
            continue
        c = int(serving[u])
        share = bandwidth_hz[c] / attached_per_cell[c]
        ue_mbps[u] = share * se[u] / 1e6

    cell_mbps = np.zeros(num_cells, dtype=float)
    for u in range(num_ues):
        if covered[u]:
            cell_mbps[int(serving[u])] += ue_mbps[u]

    return ue_mbps, cell_mbps
