"""Seeded random network generator (temporary stand-in for live data).

Places base-station sites and UEs inside the scene extent with realistic radio
config and splits each site into sectors (cells). Fully reproducible from the
config seed.

This plugs into `NetworkDataSource`; a real-data source can replace it later
without changing the rest of the pipeline.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.network.base import NetworkDataSource
from dtrapp.network.models import Cell, Network, UE

Extent = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


class RandomNetworkSource(NetworkDataSource):
    """Generates a static set of cells and UEs over the scene extent."""

    def __init__(self, config: SimulationConfig, extent_m: Extent) -> None:
        self.config = config
        self.extent_m = extent_m
        rng = np.random.default_rng(config.seed)
        self._cells = self._make_cells(rng)
        self._ues = self._make_ues(rng)

    def generate(self) -> Network:
        return Network(list(self._cells), list(self._ues))

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

    def _make_ues(self, rng: np.random.Generator) -> list[UE]:
        cfg = self.config
        min_x, min_y, max_x, max_y = self.extent_m
        xs = rng.uniform(min_x, max_x, size=cfg.num_ues)
        ys = rng.uniform(min_y, max_y, size=cfg.num_ues)
        demand = rng.uniform(5.0, 50.0, size=cfg.num_ues)
        return [
            UE(
                ue_id=f"ue{i}",
                position=(float(xs[i]), float(ys[i]), float(cfg.ue_height_m)),
                traffic_demand_mbps=float(demand[i]),
                noise_figure_db=float(cfg.ue_noise_figure_db),
            )
            for i in range(cfg.num_ues)
        ]
