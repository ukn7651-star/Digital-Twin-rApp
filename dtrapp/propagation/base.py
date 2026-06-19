"""The propagation-engine interface.

Every engine maps a NetworkSnapshot (cells + UEs placed in the 3D scene) to a
path-gain matrix `G` of shape (num_ues, num_cells) in dB, where G[u, c] is the
channel power gain from cell c to UE u. The KPI stage turns this into SINR and
throughput.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from dtrapp.network.models import NetworkSnapshot


class PropagationEngine(ABC):
    """Computes per-link path gain (dB) for a snapshot's cells and UEs."""

    @abstractmethod
    def compute_path_gain(self, snapshot: NetworkSnapshot) -> np.ndarray:
        """Return path gain (dB), shape (len(ues), len(cells))."""

    def direction_from_az_tilt(
        self, azimuth_deg: float, downtilt_deg: float
    ) -> tuple[float, float, float]:
        """Unit boresight vector from azimuth (from +x/East, CCW) and downtilt.

        Shared helper so all engines interpret antenna orientation identically.
        """
        az = np.radians(azimuth_deg)
        tilt = np.radians(downtilt_deg)
        dx = np.cos(az) * np.cos(tilt)
        dy = np.sin(az) * np.cos(tilt)
        dz = -np.sin(tilt)
        return float(dx), float(dy), float(dz)
