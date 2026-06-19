"""Configuration objects for the Digital Twin rApp throughput engine.

Everything that parameterizes a simulation run lives here as typed dataclasses.
A run can be configured in code or loaded from / saved to YAML. The config is
intentionally the single source of truth for scene extent, the (currently
random) network, the propagation solver, the KPI model, and the snapshot loop.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BoundingBox:
    """A geographic bounding box in WGS84 (lat/lon degrees).

    Order convention: south/west are the minima, north/east the maxima.
    """

    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float

    def __post_init__(self) -> None:
        if self.min_lat >= self.max_lat:
            raise ValueError("min_lat must be < max_lat")
        if self.min_lon >= self.max_lon:
            raise ValueError("min_lon must be < max_lon")
        for name, lat in (("min_lat", self.min_lat), ("max_lat", self.max_lat)):
            if not -90.0 <= lat <= 90.0:
                raise ValueError(f"{name}={lat} out of range [-90, 90]")
        for name, lon in (("min_lon", self.min_lon), ("max_lon", self.max_lon)):
            if not -180.0 <= lon <= 180.0:
                raise ValueError(f"{name}={lon} out of range [-180, 180]")

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
class GeometryConfig:
    """Stage 1 - OSM -> 3D scene parameters."""

    # Default extrusion height (m) for buildings with no height/levels tag.
    default_building_height: float = 12.0
    # Meters per OSM 'building:levels' when an explicit height is missing.
    meters_per_level: float = 3.0
    # Overpass API endpoint and request timeout (seconds).
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout_s: int = 180
    # Relative permittivity / conductivity material preset for buildings
    # (Sionna RT material name). "itu_concrete" is a sensible urban default.
    building_material: str = "itu_concrete"
    ground_material: str = "itu_concrete"


@dataclass
class AntennaConfig:
    """Antenna array geometry for transmitters and receivers."""

    num_rows: int = 1
    num_cols: int = 1
    # Sionna PlanarArray pattern: "iso", "dipole", "hw_dipole", "tr38901".
    pattern: str = "tr38901"
    polarization: str = "V"


@dataclass
class NetworkConfig:
    """Stage 2 - seeded random network (cells + UEs).

    This layer is a temporary stand-in for real network data and is consumed
    through a swappable interface (see dtrapp.network.base.NetworkDataSource).
    """

    seed: int = 0

    # Base stations / sites. Each site is split into `sectors_per_site` cells.
    num_sites: int = 3
    sectors_per_site: int = 3
    bs_height_m: float = 25.0
    tx_power_dbm: float = 46.0  # ~40 W per sector, typical macro DL

    # Radio config (shared across cells in v1; per-cell override possible later).
    carrier_freq_hz: float = 3.5e9  # 3.5 GHz (5G mid-band)
    bandwidth_hz: float = 20e6

    # Users.
    num_ues: int = 30
    ue_height_m: float = 1.5
    ue_noise_figure_db: float = 7.0

    # Optional mobility: max distance (m) a UE moves between snapshots.
    ue_mobility_m: float = 0.0

    tx_antenna: AntennaConfig = field(
        default_factory=lambda: AntennaConfig(num_rows=4, num_cols=1)
    )
    rx_antenna: AntennaConfig = field(default_factory=AntennaConfig)


@dataclass
class PropagationConfig:
    """Stage 3 - Sionna RT solver parameters."""

    # "cpu" or "cuda". CPU-only must work; GPU is an optional speedup.
    device: str = "cpu"
    # Max ray interaction depth (reflections/diffractions).
    max_depth: int = 3
    # Number of rays shot from each transmitter for the radio map.
    num_samples: int = int(1e6)
    # Radio map grid cell size (m). Coarser = faster.
    cell_size_m: float = 5.0
    los: bool = True
    reflection: bool = True
    diffraction: bool = False
    scattering: bool = False


@dataclass
class KpiConfig:
    """Stages 4-5 - SINR and throughput model parameters."""

    # Noise floor model: thermal noise = kTB * noise_figure.
    temperature_k: float = 290.0
    # SINR clip range (dB) before mapping to capacity, to keep numbers sane.
    sinr_min_db: float = -10.0
    sinr_max_db: float = 30.0
    # Spectral-efficiency cap (bit/s/Hz) to approximate practical modulation
    # limits even though v1 uses unbounded Shannon as the base model.
    max_spectral_efficiency: float = 7.0
    # Minimum received power (dBm) for a link to be considered usable; links
    # below this are treated as no-coverage (path gain -> effectively 0).
    min_rx_power_dbm: float = -140.0


@dataclass
class RunnerConfig:
    """Stage 6 - snapshot loop + output."""

    num_snapshots: int = 1
    output_dir: str = "output"
    write_csv: bool = True
    write_json: bool = True
    write_heatmap: bool = False


@dataclass
class SimulationConfig:
    """Top-level configuration aggregating every stage."""

    bbox: BoundingBox
    geometry: GeometryConfig = field(default_factory=GeometryConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    propagation: PropagationConfig = field(default_factory=PropagationConfig)
    kpi: KpiConfig = field(default_factory=KpiConfig)
    runner: RunnerConfig = field(default_factory=RunnerConfig)

    # ---- serialization helpers -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimulationConfig":
        if "bbox" not in data:
            raise ValueError("config must define a 'bbox'")
        bbox = BoundingBox(**data["bbox"])

        def build(key: str, klass):
            section = dict(data.get(key, {}))
            return _build_nested(klass, section)

        return cls(
            bbox=bbox,
            geometry=build("geometry", GeometryConfig),
            network=build("network", NetworkConfig),
            propagation=build("propagation", PropagationConfig),
            kpi=build("kpi", KpiConfig),
            runner=build("runner", RunnerConfig),
        )

    def to_yaml(self, path: str | Path) -> None:
        Path(path).write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SimulationConfig":
        data = yaml.safe_load(Path(path).read_text())
        return cls.from_dict(data)


def _build_nested(klass, section: dict[str, Any]):
    """Construct a dataclass, recursively building nested AntennaConfig fields."""
    if klass is NetworkConfig:
        for ant_key in ("tx_antenna", "rx_antenna"):
            if ant_key in section and isinstance(section[ant_key], dict):
                section[ant_key] = AntennaConfig(**section[ant_key])
    return klass(**section)
