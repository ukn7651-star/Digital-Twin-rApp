"""Multi-cell SINR computation (stage 4).

Plain NumPy so it is independent of Sionna and easy to unit-test. Linear power
is handled in milliwatts; public results are in dB / dBm.
"""

from __future__ import annotations

import numpy as np

BOLTZMANN = 1.380649e-23  # J/K


def dbm_to_mw(dbm):
    return 10.0 ** (np.asarray(dbm, dtype=float) / 10.0)


def thermal_noise_dbm(bandwidth_hz, noise_figure_db=0.0, temperature_k=290.0):
    """Thermal noise power in dBm: 10*log10(kTB / 1mW) + noise figure."""
    noise_mw = BOLTZMANN * temperature_k * np.asarray(bandwidth_hz, dtype=float) * 1e3
    return 10.0 * np.log10(noise_mw) + np.asarray(noise_figure_db, dtype=float)


def compute_received_power_dbm(path_gain_db, tx_power_dbm):
    """Received power per (UE, cell): Rx[u,c] = Ptx[c] + G[u,c] (dBm)."""
    return np.asarray(path_gain_db, dtype=float) + np.asarray(tx_power_dbm, dtype=float)


def associate_cells(rx_power_dbm) -> np.ndarray:
    """Assign each UE to its strongest cell; returns the serving cell index."""
    return np.argmax(rx_power_dbm, axis=1)


def compute_sinr_db(rx_power_dbm, serving, noise_dbm) -> np.ndarray:
    """SINR per UE = serving signal / (other cells' interference + noise), in dB."""
    rx_mw = dbm_to_mw(rx_power_dbm)
    u = np.arange(rx_mw.shape[0])
    signal_mw = rx_mw[u, serving]
    interference_mw = rx_mw.sum(axis=1) - signal_mw
    noise_mw = dbm_to_mw(noise_dbm)
    sinr_lin = signal_mw / (interference_mw + noise_mw)
    return 10.0 * np.log10(np.maximum(sinr_lin, 1e-30))
