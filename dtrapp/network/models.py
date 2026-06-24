"""Data structures describing the (static) network.

Positions are in the local ENU metric frame (metres, z up) shared with the
geometry stage, so cells and UEs drop straight into the Sionna scene.
"""

from __future__ import annotations

from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass
class Cell:
    """One antenna sector of a base station = one cell.

    A UE attaches to exactly one cell; all other cells become interference.
    """

    cell_id: str
    position: Vec3  # (x, y, z) metres, z = antenna height
    azimuth_deg: float  # sector boresight bearing (0 = +x / East)
    tx_power_dbm: float
    carrier_freq_hz: float
    bandwidth_hz: float


@dataclass
class UE:
    """A user device receiving downlink data."""

    ue_id: str
    position: Vec3  # (x, y, z) metres, z = device height
    traffic_demand_mbps: float
    noise_figure_db: float


@dataclass
class Network:
    """The whole network: every cell and every UE."""

    cells: list[Cell]
    ues: list[UE]
