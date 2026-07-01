"""Configuration for the Digital Twin rApp throughput engine.

One flat dataclass holds every setting for a run. It can be built in code or
loaded from a YAML file. Keeping it flat (no nested config objects) keeps the
whole engine easy to read - the brief itself lists the parameters as a flat set
(bbox, seed, #cells, #UEs, freq, bandwidth, ...).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BoundingBox:
    """A geographic bounding box in WGS84 (lat/lon degrees), south/west first."""

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def __post_init__(self) -> None:
        if self.min_lat >= self.max_lat:
            raise ValueError("min_lat must be < max_lat")
        if self.min_lon >= self.max_lon:
            raise ValueError("min_lon must be < max_lon")

    @property
    def center(self) -> tuple[float, float]:
        """(lat, lon) of the box center, used as the local scene origin."""
        return (
            0.5 * (self.min_lat + self.max_lat),
            0.5 * (self.min_lon + self.max_lon),
        )

    def as_overpass_bbox(self) -> str:
        """Overpass expects 'south,west,north,east'."""
        return f"{self.min_lat},{self.min_lon},{self.max_lat},{self.max_lon}"


@dataclass
class SimulationConfig:
    """Every parameter for one simulation run."""

    bbox: BoundingBox

    # --- geometry (stage 1) ---
    default_building_height_m: float = 12.0
    meters_per_level: float = 3.0
    building_material: str = "itu_concrete"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout_s: int = 180

    # --- network (stage 2): seeded random stand-in for real data ---
    seed: int = 0
    num_sites: int = 3
    sectors_per_site: int = 3
    bs_height_m: float = 25.0
    tx_power_dbm: float = 46.0
    carrier_freq_hz: float = 3.5e9
    bandwidth_hz: float = 20e6
    num_ues: int = 30
    ue_height_m: float = 1.5
    ue_noise_figure_db: float = 7.0

    # --- propagation (stage 3): Sionna RT ---
    max_depth: int = 3  # ray interaction depth (reflections)

    # --- antennas (stage 3) ---
    bs_antenna_rows: int = 4
    bs_antenna_cols: int = 1
    bs_antenna_pattern: str = "tr38901"  # 3GPP sector pattern; "iso", "dipole", ...
    bs_antenna_polarization: str = "V"  # "V", "H", "VH" (dual), "cross"
    ue_antenna_rows: int = 1
    ue_antenna_cols: int = 1
    ue_antenna_pattern: str = "iso"
    ue_antenna_polarization: str = "V"
    antenna_spacing: float = 0.5  # element spacing, multiples of wavelength
    downtilt_deg: float = 8.0  # BS sector electrical downtilt

    # --- kpi (stages 4-5): Sionna SYS link-level chain ---
    temperature_k: float = 290.0
    bler_target: float = 0.1  # link-adaptation BLER target
    mcs_table_index: int = 1  # 5G-NR MCS table (1: up to 64QAM, 2: up to 256QAM)
    subcarrier_spacing_hz: float = 30.0e3  # OFDM numerology for the SYS resource grid
    num_subcarriers: int = 128  # representative sub-band for the post-eq SINR / MCS
    num_ofdm_symbols: int = 12  # OFDM symbols per slot in the SYS resource grid

    # --- scheduling (stage 5): how each cell shares its airtime among its UEs ---
    #   "equal"          -> equal airtime (fairness), rate_i = (B/K) * SE_i
    #   "max_throughput" -> airtime weighted toward better-channel UEs (t_i ~ SE_i);
    #                       higher total cell throughput, less fair (max-C/I flavour)
    # On a static snapshot a real PF scheduler ~= "equal"; the meaningful contrast is
    # fairness vs throughput-greedy, so these are the two comparable modes.
    scheduling: str = "equal"

    # --- runner (stage 6) ---
    output_dir: str = "output"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimulationConfig":
        data = dict(data)
        if "bbox" not in data:
            raise ValueError("config must define a 'bbox'")
        bbox_data = {k: float(v) for k, v in data.pop("bbox").items()}
        bbox = BoundingBox(**bbox_data)
        # Coerce numeric fields to their declared type. YAML parses unsigned
        # scientific notation (e.g. ``3.5e9``, ``30.0e3``) as a string, so we
        # cast here to keep config values numeric regardless of how they're written.
        casters = {"float": float, "int": int}
        for f in fields(cls):
            if f.name in data and isinstance(data[f.name], str):
                cast = casters.get(getattr(f, "type", None))
                if cast is not None:
                    data[f.name] = cast(data[f.name])
        return cls(bbox=bbox, **data)

    def to_yaml(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SimulationConfig":
        return cls.from_dict(yaml.safe_load(Path(path).read_text()))
