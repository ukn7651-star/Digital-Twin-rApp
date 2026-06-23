"""SINR -> downlink throughput with per-cell resource sharing (stage 5).

v1 model (Shannon capacity):
  spectral efficiency  SE = log2(1 + SINR_lin)            [bit/s/Hz]
  resource sharing     each cell splits its bandwidth equally among its
                       attached UEs, so a UE alone on a cell gets full bandwidth
  per-UE throughput    R_u = (B_cell / K_cell) * SE_u     [bit/s]
  per-cell throughput  R_cell = sum of its UEs' R_u

This is the clean seam for future upgrades: replace this function with 5G-NR MCS
tables, MIMO layers, and a PRB scheduler without touching the SINR or runner
layers (the path towards the full Rimedo-Labs-style model).
"""

from __future__ import annotations

import numpy as np


def spectral_efficiency(sinr_db) -> np.ndarray:
    """Shannon spectral efficiency (bit/s/Hz)."""
    return np.log2(1.0 + 10.0 ** (np.asarray(sinr_db, dtype=float) / 10.0))


def shannon_throughput(sinr_db, serving, bandwidth_hz, num_cells):
    """Per-UE and per-cell downlink throughput in Mbps.

    sinr_db: (num_ues,)  serving: (num_ues,) cell index  bandwidth_hz: (num_cells,)
    Returns (ue_mbps (num_ues,), cell_mbps (num_cells,)).
    """
    serving = np.asarray(serving)
    bandwidth_hz = np.asarray(bandwidth_hz, dtype=float)
    se = spectral_efficiency(sinr_db)

    attached = np.bincount(serving, minlength=num_cells).astype(float)
    ue_mbps = bandwidth_hz[serving] / attached[serving] * se / 1e6

    cell_mbps = np.zeros(num_cells, dtype=float)
    np.add.at(cell_mbps, serving, ue_mbps)
    return ue_mbps, cell_mbps
