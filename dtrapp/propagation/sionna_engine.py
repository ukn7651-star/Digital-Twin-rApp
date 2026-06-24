"""Stage 3 - propagation: Sionna RT ray tracing.

Loads the Mitsuba scene built in stage 1, places one Transmitter per cell and
one Receiver per UE, runs the Sionna RT `PathSolver`, and reduces the path
coefficients into a per-link path-gain matrix (dB), shape (num_ues, num_cells).

Ray tracing is the engine: it runs every time the twin produces throughput.
v1 assumes all cells share one carrier frequency (a single Sionna scene has one
frequency); per-cell carriers are a future extension.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.network.models import Network


def _boresight(azimuth_deg: float, downtilt_deg: float = 8.0) -> tuple[float, float, float]:
    az, tilt = np.radians(azimuth_deg), np.radians(downtilt_deg)
    return (
        float(np.cos(az) * np.cos(tilt)),
        float(np.sin(az) * np.cos(tilt)),
        float(-np.sin(tilt)),
    )


class SionnaPropagationEngine:
    """Computes per-link path gain (dB) for the network via ray tracing."""

    def __init__(self, scene_xml, config: SimulationConfig) -> None:
        self.config = config
        try:
            from sionna.rt import (
                PathSolver,
                PlanarArray,
                Receiver,
                Transmitter,
                load_scene,
            )
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "Sionna RT is required. Install it with `pip install sionna-rt`."
            ) from exc

        self._scene = load_scene(str(scene_xml))
        self._Transmitter = Transmitter
        self._Receiver = Receiver
        self._solver = PathSolver()
        # One fixed antenna array for all transmitters / receivers (v1).
        self._scene.tx_array = PlanarArray(
            num_rows=4, num_cols=1, pattern="tr38901", polarization="V"
        )
        self._scene.rx_array = PlanarArray(
            num_rows=1, num_cols=1, pattern="iso", polarization="V"
        )

    def compute_path_gain(self, network: Network) -> np.ndarray:
        cells, ues = network.cells, network.ues
        if not cells or not ues:
            return np.zeros((len(ues), len(cells)), dtype=float)

        scene = self._scene
        scene.frequency = float(cells[0].carrier_freq_hz)
        self._clear()

        for cell in cells:
            px, py, pz = cell.position
            dx, dy, dz = _boresight(cell.azimuth_deg)
            scene.add(
                self._Transmitter(
                    name=cell.cell_id,
                    position=[px, py, pz],
                    look_at=[px + dx, py + dy, pz + dz],
                    power_dbm=float(cell.tx_power_dbm),
                )
            )
        for ue in ues:
            scene.add(self._Receiver(name=ue.ue_id, position=list(ue.position)))

        paths = self._solver(scene, max_depth=self.config.max_depth)
        return self._path_gain_db(paths, len(ues), len(cells))

    def _clear(self) -> None:
        for name in list(self._scene.transmitters.keys()):
            self._scene.remove(name)
        for name in list(self._scene.receivers.keys()):
            self._scene.remove(name)

    @staticmethod
    def _path_gain_db(paths, num_ues: int, num_cells: int) -> np.ndarray:
        a = paths.a
        if isinstance(a, (tuple, list)) and len(a) == 2:
            amp2 = np.array(a[0]) ** 2 + np.array(a[1]) ** 2
        else:
            amp2 = np.abs(np.array(a)) ** 2
        # amp2: (num_rx, num_rx_ant, num_tx, num_tx_ant, num_paths).
        gain_lin = amp2.sum(axis=(1, 3, 4)).reshape(num_ues, num_cells)
        return 10.0 * np.log10(np.maximum(gain_lin, 1e-30))
