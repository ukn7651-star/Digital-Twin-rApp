"""Result containers for one snapshot's KPIs (per-UE and per-cell)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class UEKpi:
    snapshot: int
    ue_id: str
    serving_cell: str
    x: float
    y: float
    z: float
    sinr_db: float
    spectral_efficiency: float
    throughput_mbps: float
    traffic_demand_mbps: float
    covered: bool


@dataclass
class CellKpi:
    snapshot: int
    cell_id: str
    num_attached: int
    throughput_mbps: float
    x: float
    y: float
    z: float


@dataclass
class SnapshotKpi:
    index: int
    ues: list[UEKpi] = field(default_factory=list)
    cells: list[CellKpi] = field(default_factory=list)

    def ue_rows(self) -> list[dict]:
        return [asdict(u) for u in self.ues]

    def cell_rows(self) -> list[dict]:
        return [asdict(c) for c in self.cells]

    def to_dict(self) -> dict:
        return {
            "snapshot": self.index,
            "ues": self.ue_rows(),
            "cells": self.cell_rows(),
        }
