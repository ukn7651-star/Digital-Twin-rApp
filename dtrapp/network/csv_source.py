"""Real-site network data source: cells (and optionally UEs) from CSV.

This is the "swap the random stand-in for real data" implementation of
``NetworkDataSource``. Cell rows use WGS84 lat/lon (the format of open
databases such as OpenCelliD) and are projected into the scene's local ENU
frame with the same projection the geometry stage uses, so real sites drop
straight into the ray-traced scene.

Cells CSV columns (header required; * = required, rest fall back to config):
    lat*, lon*, cell_id, azimuth_deg, height_m, tx_power_dbm,
    carrier_freq_hz, bandwidth_hz, sectors
If ``azimuth_deg`` is missing and ``sectors`` (default 3) is given, the site is
split into evenly spaced sectors - one Cell per sector, like the random source.

UEs CSV columns:
    lat*, lon*, ue_id, height_m, traffic_demand_mbps, noise_figure_db

Rows outside the configured bounding box are skipped with a warning count, so a
raw country-wide OpenCelliD export can be pointed at directly.
"""

from __future__ import annotations

import csv
from pathlib import Path

from dtrapp.config import SimulationConfig
from dtrapp.geometry.projection import LocalProjection
from dtrapp.network.base import NetworkDataSource
from dtrapp.network.models import Cell, Network, UE
from dtrapp.network.random_source import RandomNetworkSource

Extent = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


def _get(row: dict, key: str, default: float | None = None) -> float | None:
    val = row.get(key)
    if val is None or str(val).strip() == "":
        return default
    return float(val)


class CsvNetworkSource(NetworkDataSource):
    """Cells/UEs from CSV files (lat/lon), projected into the scene frame."""

    def __init__(self, config: SimulationConfig, extent_m: Extent) -> None:
        self.config = config
        self.extent_m = extent_m
        lat0, lon0 = config.bbox.center
        self._proj = LocalProjection(lat0, lon0)
        self.num_skipped = 0  # rows outside the bbox (updated by _load_cells)
        self._cells = self._load_cells(Path(config.cells_csv)) if config.cells_csv else None
        self._ues = self._load_ues(Path(config.ues_csv)) if config.ues_csv else None

    def generate(self) -> Network:
        cells, ues = self._cells, self._ues
        if cells is None or ues is None:
            # Fall back to the seeded random source for whichever half is missing
            # (typical: real cells + random UE drops).
            rand = RandomNetworkSource(self.config, self.extent_m).generate()
            cells = cells if cells is not None else rand.cells
            ues = ues if ues is not None else rand.ues
        if not cells:
            raise ValueError(f"no cells inside the bbox in {self.config.cells_csv}")
        return Network(list(cells), list(ues))

    def _in_bbox(self, lat: float, lon: float) -> bool:
        b = self.config.bbox
        return b.min_lat <= lat <= b.max_lat and b.min_lon <= lon <= b.max_lon

    def _load_cells(self, path: Path) -> list[Cell]:
        cfg = self.config
        cells: list[Cell] = []
        skipped = 0
        with path.open(newline="") as fh:
            for i, row in enumerate(csv.DictReader(fh)):
                lat, lon = _get(row, "lat"), _get(row, "lon")
                if lat is None or lon is None:
                    raise ValueError(f"{path}:{i + 2}: cells CSV needs 'lat' and 'lon'")
                if not self._in_bbox(lat, lon):
                    skipped += 1
                    continue
                x, y = self._proj.to_local(lat, lon)
                z = _get(row, "height_m", cfg.bs_height_m)
                site_id = row.get("cell_id") or f"site{i}"
                tx = _get(row, "tx_power_dbm", cfg.tx_power_dbm)
                fc = _get(row, "carrier_freq_hz", cfg.carrier_freq_hz)
                bw = _get(row, "bandwidth_hz", cfg.bandwidth_hz)
                az = _get(row, "azimuth_deg")
                if az is not None:  # one explicit sector
                    cells.append(Cell(site_id, (x, y, z), az, tx, fc, bw))
                    continue
                sectors = int(_get(row, "sectors", float(cfg.sectors_per_site)))
                for sec in range(max(sectors, 1)):
                    cells.append(
                        Cell(
                            cell_id=f"{site_id}-c{sec}",
                            position=(x, y, z),
                            azimuth_deg=(sec * 360.0 / max(sectors, 1)) % 360.0,
                            tx_power_dbm=tx,
                            carrier_freq_hz=fc,
                            bandwidth_hz=bw,
                        )
                    )
        self.num_skipped = skipped
        return cells

    def _load_ues(self, path: Path) -> list[UE]:
        cfg = self.config
        ues: list[UE] = []
        with path.open(newline="") as fh:
            for i, row in enumerate(csv.DictReader(fh)):
                lat, lon = _get(row, "lat"), _get(row, "lon")
                if lat is None or lon is None:
                    raise ValueError(f"{path}:{i + 2}: UEs CSV needs 'lat' and 'lon'")
                if not self._in_bbox(lat, lon):
                    continue
                x, y = self._proj.to_local(lat, lon)
                ues.append(
                    UE(
                        ue_id=row.get("ue_id") or f"ue{i}",
                        position=(x, y, _get(row, "height_m", cfg.ue_height_m)),
                        traffic_demand_mbps=_get(row, "traffic_demand_mbps", 0.0),
                        noise_figure_db=_get(row, "noise_figure_db", cfg.ue_noise_figure_db),
                    )
                )
        return ues
