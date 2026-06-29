"""Data structures describing the network at one snapshot.

Positions are in the local ENU metric frame (meters, z up) shared with the
geometry stage, so cells and UEs can be dropped straight into the Sionna scene.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dtrapp.config import AntennaConfig

Vec3 = tuple[float, float, float]


@dataclass
class Cell:
    """One antenna sector of a base station = one cell.

    A UE attaches to exactly one cell; all other cells become interference.
    """

    cell_id: str
    site_id: int
    sector: int
    position: Vec3  # (x, y, z) meters, z = antenna height
    azimuth_deg: float  # bearing of the sector boresight (0 = +x / East)
    downtilt_deg: float
    tx_power_dbm: float
    carrier_freq_hz: float
    bandwidth_hz: float
    antenna: AntennaConfig = field(default_factory=AntennaConfig)


@dataclass
class UE:
    """A user device receiving downlink data."""

    ue_id: str
    position: Vec3  # (x, y, z) meters, z = device height
    traffic_demand_mbps: float
    noise_figure_db: float
    antenna: AntennaConfig = field(default_factory=AntennaConfig)


@dataclass
class NetworkSnapshot:
    """The whole network frozen at one instant."""

    index: int
    cells: list[Cell]
    ues: list[UE]
