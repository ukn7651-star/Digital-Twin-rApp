"""Sionna RT propagation engine (stage 3) - the v1 ray-tracing engine.

Loads the Mitsuba scene built in stage 1, places one Transmitter per cell and
one Receiver per UE, runs the Sionna RT `PathSolver`, and reduces the resulting
path coefficients into a per-link path-gain matrix (dB), shape (num_ues,
num_cells).

Notes / v1 assumptions
----------------------
* Channel coefficients ``paths.a`` carry the channel power gain ``|a|^2``
  independent of transmit power, so the KPI stage adds ``tx_power_dbm`` itself.
* A single Sionna scene has one carrier frequency and one TX/RX array, so v1
  assumes all cells share ``carrier_freq_hz`` and antenna config (taken from the
  first cell / first UE). Per-cell carriers are a future extension.
* Runs on CPU (Dr.Jit LLVM backend) by default; Sionna RT automatically uses a
  CUDA backend when a GPU is available, giving the GPU-ready speedup for free.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import PropagationConfig
from dtrapp.network.models import NetworkSnapshot
from dtrapp.propagation.base import PropagationEngine


class SionnaPropagationEngine(PropagationEngine):
    def __init__(self, scene_xml, config: PropagationConfig | None = None) -> None:
        self.scene_xml = str(scene_xml)
        self.config = config or PropagationConfig()
        # Lazy, explicit import so the rest of the package works without Sionna.
        try:
            from sionna.rt import (  # noqa: F401
                PathSolver,
                PlanarArray,
                Receiver,
                Transmitter,
                load_scene,
            )
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "Sionna RT is required for the ray-tracing engine. Install it "
                "with `pip install sionna-rt`. (For pipeline development without "
                "Sionna, explicitly select the 'analytical' engine.)"
            ) from exc

        self._rt = __import__("sionna.rt", fromlist=["*"])
        self._scene = load_scene(self.scene_xml)
        self._PlanarArray = PlanarArray
        self._Transmitter = Transmitter
        self._Receiver = Receiver
        self._solver = PathSolver()

    def compute_path_gain(self, snapshot: NetworkSnapshot) -> np.ndarray:
        cells = snapshot.cells
        ues = snapshot.ues
        if not cells or not ues:
            return np.zeros((len(ues), len(cells)), dtype=float)

        scene = self._scene
        scene.frequency = float(cells[0].carrier_freq_hz)

        tx_ant = cells[0].antenna
        rx_ant = ues[0].antenna
        scene.tx_array = self._PlanarArray(
            num_rows=tx_ant.num_rows,
            num_cols=tx_ant.num_cols,
            pattern=tx_ant.pattern,
            polarization=tx_ant.polarization,
        )
        scene.rx_array = self._PlanarArray(
            num_rows=rx_ant.num_rows,
            num_cols=rx_ant.num_cols,
            pattern=rx_ant.pattern,
            polarization=rx_ant.polarization,
        )

        self._clear_radio_devices()

        for cell in cells:
            px, py, pz = cell.position
            dx, dy, dz = self.direction_from_az_tilt(
                cell.azimuth_deg, cell.downtilt_deg
            )
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

        paths = self._solver(
            scene,
            max_depth=self.config.max_depth,
            los=self.config.los,
            specular_reflection=self.config.reflection,
            diffuse_reflection=self.config.scattering,
            diffraction=self.config.diffraction,
            samples_per_src=self.config.num_samples,
        )

        return self._path_gain_db(paths, len(ues), len(cells))

    # ---- helpers ---------------------------------------------------------------

    def _clear_radio_devices(self) -> None:
        scene = self._scene
        for name in list(scene.transmitters.keys()):
            scene.remove(name)
        for name in list(scene.receivers.keys()):
            scene.remove(name)

    @staticmethod
    def _path_gain_db(paths, num_ues: int, num_cells: int) -> np.ndarray:
        a = paths.a
        if isinstance(a, (tuple, list)) and len(a) == 2:
            real = np.array(a[0])
            imag = np.array(a[1])
            amp2 = real**2 + imag**2
        else:
            arr = np.array(a)
            amp2 = np.abs(arr) ** 2
        # amp2 shape: (num_rx, num_rx_ant, num_tx, num_tx_ant, num_paths).
        # Path gain per (rx, tx) sums over antenna and path dimensions.
        gain_lin = amp2.sum(axis=(1, 3, 4))  # (num_rx, num_tx) = (num_ues, num_cells)
        gain_lin = np.asarray(gain_lin, dtype=float).reshape(num_ues, num_cells)
        return 10.0 * np.log10(np.maximum(gain_lin, 1e-30))
