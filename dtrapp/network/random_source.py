"""Seeded random network generator (temporary stand-in for live data).

Places base-station sites and UEs inside the scene extent with realistic radio
config, splits each site into sectors (cells), and applies optional UE mobility
between snapshots. Fully reproducible from the config seed.

This plugs into `NetworkDataSource`; a real-data source can replace it later
without changing the rest of the pipeline.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.network.base import NetworkDataSource
from dtrapp.network.models import Cell, NetworkSnapshot, UE

Extent = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


class RandomNetworkSource(NetworkDataSource):
    """Generates static cells and (optionally mobile) UEs over snapshots."""

    def __init__(self, config: SimulationConfig, extent_m: Extent) -> None:
        self.config = config
        self.extent_m = extent_m
        self._n = max(1, int(config.num_snapshots))
        rng = np.random.default_rng(config.seed)
        self._cells = self._make_cells(rng)
        self._ue_xy = self._make_ue_positions(rng)
        self._ue_demand = rng.uniform(5.0, 50.0, size=config.num_ues)

    @property
    def num_snapshots(self) -> int:
        return self._n

    def snapshot(self, index: int) -> NetworkSnapshot:
        if not 0 <= index < self._n:
            raise IndexError(f"snapshot index {index} out of range")
        return NetworkSnapshot(index, list(self._cells), self._make_ues(index))

    def _make_cells(self, rng: np.random.Generator) -> list[Cell]:
        cfg = self.config
        min_x, min_y, max_x, max_y = self.extent_m
        cells: list[Cell] = []
        for site in range(cfg.num_sites):
            sx = rng.uniform(min_x, max_x)
            sy = rng.uniform(min_y, max_y)
            base_az = rng.uniform(0.0, 360.0)
            for sector in range(cfg.sectors_per_site):
                az = (base_az + sector * 360.0 / cfg.sectors_per_site) % 360.0
                cells.append(
                    Cell(
                        cell_id=f"s{site}-c{sector}",
                        position=(float(sx), float(sy), float(cfg.bs_height_m)),
                        azimuth_deg=float(az),
                        tx_power_dbm=float(cfg.tx_power_dbm),
                        carrier_freq_hz=float(cfg.carrier_freq_hz),
                        bandwidth_hz=float(cfg.bandwidth_hz),
                    )
                )
        return cells

    def _make_ue_positions(self, rng: np.random.Generator) -> np.ndarray:
        min_x, min_y, max_x, max_y = self.extent_m
        return np.column_stack(
            (
                rng.uniform(min_x, max_x, size=self.config.num_ues),
                rng.uniform(min_y, max_y, size=self.config.num_ues),
            )
        )

    def _make_ues(self, index: int) -> list[UE]:
        cfg = self.config
        xy = self._ue_xy
        if cfg.ue_mobility_m > 0.0 and index > 0:
            rng = np.random.default_rng([cfg.seed, index])
            angle = rng.uniform(0.0, 2 * np.pi, size=len(xy))
            radius = cfg.ue_mobility_m * np.sqrt(rng.uniform(0.0, 1.0, size=len(xy)))
            xy = xy + np.column_stack((radius * np.cos(angle), radius * np.sin(angle)))
        return [
            UE(
                ue_id=f"ue{i}",
                position=(float(xy[i, 0]), float(xy[i, 1]), float(cfg.ue_height_m)),
                traffic_demand_mbps=float(self._ue_demand[i]),
                noise_figure_db=float(cfg.ue_noise_figure_db),
            )
            for i in range(len(xy))
        ]
