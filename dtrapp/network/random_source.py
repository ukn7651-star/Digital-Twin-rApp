"""Seeded random network generator (temporary stand-in for live data).

Places base-station sites and UEs inside the scene extent with realistic radio
config, splits each site into sectors (cells), and applies optional UE mobility
between snapshots. Fully reproducible from `NetworkConfig.seed`.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import NetworkConfig
from dtrapp.network.base import NetworkDataSource
from dtrapp.network.models import Cell, NetworkSnapshot, UE

Extent = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


class RandomNetworkSource(NetworkDataSource):
    """Generates cells (static) and UEs (optionally mobile) over snapshots."""

    def __init__(
        self,
        config: NetworkConfig,
        extent_m: Extent,
        num_snapshots: int = 1,
        site_inset_m: float = 30.0,
    ) -> None:
        self.config = config
        self.extent_m = extent_m
        self._num_snapshots = max(1, int(num_snapshots))
        self._site_inset_m = site_inset_m

        rng = np.random.default_rng(config.seed)
        self._cells = self._make_cells(rng)
        self._ue_base_xy, self._ue_demand = self._make_ue_base(rng)

    # ---- public API ------------------------------------------------------------

    @property
    def num_snapshots(self) -> int:
        return self._num_snapshots

    def snapshot(self, index: int) -> NetworkSnapshot:
        if not 0 <= index < self._num_snapshots:
            raise IndexError(f"snapshot index {index} out of range")
        ues = self._make_ues(index)
        # Cells are static; copy is unnecessary as Cell is treated read-only.
        return NetworkSnapshot(index=index, cells=list(self._cells), ues=ues)

    # ---- generation helpers ----------------------------------------------------

    def _inset_extent(self) -> Extent:
        min_x, min_y, max_x, max_y = self.extent_m
        m = self._site_inset_m
        # Guard against insets larger than the extent.
        if max_x - min_x <= 2 * m or max_y - min_y <= 2 * m:
            return self.extent_m
        return (min_x + m, min_y + m, max_x - m, max_y - m)

    def _make_cells(self, rng: np.random.Generator) -> list[Cell]:
        cfg = self.config
        min_x, min_y, max_x, max_y = self._inset_extent()
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
                        site_id=site,
                        sector=sector,
                        position=(float(sx), float(sy), float(cfg.bs_height_m)),
                        azimuth_deg=float(az),
                        downtilt_deg=8.0,
                        tx_power_dbm=float(cfg.tx_power_dbm),
                        carrier_freq_hz=float(cfg.carrier_freq_hz),
                        bandwidth_hz=float(cfg.bandwidth_hz),
                        antenna=cfg.tx_antenna,
                    )
                )
        return cells

    def _make_ue_base(self, rng: np.random.Generator):
        cfg = self.config
        min_x, min_y, max_x, max_y = self.extent_m
        xy = np.column_stack(
            (
                rng.uniform(min_x, max_x, size=cfg.num_ues),
                rng.uniform(min_y, max_y, size=cfg.num_ues),
            )
        )
        demand = rng.uniform(5.0, 50.0, size=cfg.num_ues)
        return xy, demand

    def _make_ues(self, index: int) -> list[UE]:
        cfg = self.config
        xy = self._ue_base_xy
        if cfg.ue_mobility_m > 0.0 and index > 0:
            # Independent per-snapshot displacement within a disk of given radius.
            rng_i = np.random.default_rng([cfg.seed, index])
            angles = rng_i.uniform(0.0, 2 * np.pi, size=len(xy))
            radii = cfg.ue_mobility_m * np.sqrt(rng_i.uniform(0.0, 1.0, size=len(xy)))
            offset = np.column_stack((radii * np.cos(angles), radii * np.sin(angles)))
            xy = xy + offset
            xy = self._clip_to_extent(xy)

        ues: list[UE] = []
        for i in range(len(xy)):
            ues.append(
                UE(
                    ue_id=f"ue{i}",
                    position=(float(xy[i, 0]), float(xy[i, 1]), float(cfg.ue_height_m)),
                    traffic_demand_mbps=float(self._ue_demand[i]),
                    noise_figure_db=float(cfg.ue_noise_figure_db),
                    antenna=cfg.rx_antenna,
                )
            )
        return ues

    def _clip_to_extent(self, xy: np.ndarray) -> np.ndarray:
        min_x, min_y, max_x, max_y = self.extent_m
        xy[:, 0] = np.clip(xy[:, 0], min_x, max_x)
        xy[:, 1] = np.clip(xy[:, 1], min_y, max_y)
        return xy
