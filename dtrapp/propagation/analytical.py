"""Analytical log-distance propagation engine (DEVELOPMENT/TEST ONLY).

This is NOT ray tracing. It exists so the network -> KPI -> output pipeline can
be exercised on machines without Sionna RT or a GPU. It uses a log-distance
path-loss model plus a 3GPP-style sectorized antenna pattern, which is enough to
satisfy the sanity check that a closer / better-aligned UE gets higher
throughput. Select it explicitly; it is never a silent fallback for Sionna RT.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import PropagationConfig
from dtrapp.network.models import NetworkSnapshot
from dtrapp.propagation.base import PropagationEngine

_C = 299_792_458.0  # speed of light, m/s


class AnalyticalPropagationEngine(PropagationEngine):
    def __init__(
        self,
        scene_xml=None,
        config: PropagationConfig | None = None,
        path_loss_exponent: float = 3.0,
        antenna_max_gain_dbi: float = 15.0,
        h_3db_deg: float = 65.0,
        front_back_db: float = 30.0,
    ) -> None:
        self.scene_xml = scene_xml
        self.config = config or PropagationConfig()
        self.n = path_loss_exponent
        self.max_gain = antenna_max_gain_dbi
        self.h_3db = h_3db_deg
        self.fb = front_back_db

    def compute_path_gain(self, snapshot: NetworkSnapshot) -> np.ndarray:
        cells = snapshot.cells
        ues = snapshot.ues
        gain = np.zeros((len(ues), len(cells)), dtype=float)

        for c, cell in enumerate(cells):
            cx, cy, cz = cell.position
            wavelength = _C / cell.carrier_freq_hz
            bx, by, _ = self.direction_from_az_tilt(
                cell.azimuth_deg, cell.downtilt_deg
            )
            boresight_az = np.arctan2(by, bx)
            for u, ue in enumerate(ues):
                ux, uy, uz = ue.position
                d = float(np.sqrt((ux - cx) ** 2 + (uy - cy) ** 2 + (uz - cz) ** 2))
                d = max(d, 1.0)
                # Free-space at 1 m reference, then log-distance beyond.
                fspl_1m = 20.0 * np.log10(4.0 * np.pi / wavelength)
                pl_db = fspl_1m + 10.0 * self.n * np.log10(d)
                # Horizontal antenna pattern.
                ang = np.arctan2(uy - cy, ux - cx) - boresight_az
                ang = (ang + np.pi) % (2 * np.pi) - np.pi
                ang_deg = np.degrees(ang)
                att = min(12.0 * (ang_deg / self.h_3db) ** 2, self.fb)
                ant_gain = self.max_gain - att
                gain[u, c] = ant_gain - pl_db
        return gain
