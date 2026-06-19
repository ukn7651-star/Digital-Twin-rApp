"""Multi-cell SINR computation (stage 4).

All functions operate on plain NumPy arrays so they are independent of Sionna
and trivially unit-testable. Linear power is handled in milliwatts; the public
results are in dB / dBm.
"""

from __future__ import annotations

import numpy as np

BOLTZMANN = 1.380649e-23  # J/K


def dbm_to_mw(dbm: np.ndarray | float) -> np.ndarray:
    return 10.0 ** (np.asarray(dbm, dtype=float) / 10.0)


def mw_to_dbm(mw: np.ndarray | float) -> np.ndarray:
    mw = np.asarray(mw, dtype=float)
    return 10.0 * np.log10(np.maximum(mw, 1e-300))


def thermal_noise_dbm(
    bandwidth_hz: np.ndarray | float,
    noise_figure_db: np.ndarray | float = 0.0,
    temperature_k: float = 290.0,
) -> np.ndarray:
    """Thermal noise power in dBm: 10*log10(kTB / 1mW) + noise figure."""
    bandwidth_hz = np.asarray(bandwidth_hz, dtype=float)
    noise_w = BOLTZMANN * temperature_k * bandwidth_hz
    noise_mw = noise_w * 1e3
    return 10.0 * np.log10(noise_mw) + np.asarray(noise_figure_db, dtype=float)


def compute_received_power_dbm(
    path_gain_db: np.ndarray, tx_power_dbm: np.ndarray
) -> np.ndarray:
    """Received power per (UE, cell): Rx[u,c] = Ptx[c] + G[u,c]  (dBm).

    path_gain_db: (num_ues, num_cells), channel power gain in dB (<= 0).
    tx_power_dbm: (num_cells,).
    """
    path_gain_db = np.asarray(path_gain_db, dtype=float)
    tx_power_dbm = np.asarray(tx_power_dbm, dtype=float)
    return path_gain_db + tx_power_dbm[np.newaxis, :]


def associate_cells(
    rx_power_dbm: np.ndarray, min_rx_power_dbm: float = -np.inf
) -> tuple[np.ndarray, np.ndarray]:
    """Assign each UE to its strongest cell.

    Returns (serving_idx, covered) where serving_idx[u] is the cell index and
    covered[u] is False when even the best cell is below `min_rx_power_dbm`.
    """
    serving = np.argmax(rx_power_dbm, axis=1)
    best = rx_power_dbm[np.arange(rx_power_dbm.shape[0]), serving]
    covered = best >= min_rx_power_dbm
    return serving, covered


def compute_sinr_db(
    rx_power_dbm: np.ndarray,
    serving: np.ndarray,
    noise_dbm: np.ndarray,
    sinr_min_db: float = -np.inf,
    sinr_max_db: float = np.inf,
) -> np.ndarray:
    """SINR per UE = serving signal / (sum of other cells + noise), in dB.

    rx_power_dbm: (num_ues, num_cells).
    serving: (num_ues,) serving cell index per UE.
    noise_dbm: scalar or (num_ues,) noise power in dBm.
    """
    rx_mw = dbm_to_mw(rx_power_dbm)
    num_ues = rx_mw.shape[0]
    u_idx = np.arange(num_ues)

    signal_mw = rx_mw[u_idx, serving]
    total_mw = rx_mw.sum(axis=1)
    interference_mw = total_mw - signal_mw

    noise_mw = dbm_to_mw(noise_dbm)
    if noise_mw.ndim == 0:
        noise_mw = np.full(num_ues, float(noise_mw))

    sinr_lin = signal_mw / (interference_mw + noise_mw)
    sinr_db = 10.0 * np.log10(np.maximum(sinr_lin, 1e-30))
    return np.clip(sinr_db, sinr_min_db, sinr_max_db)
