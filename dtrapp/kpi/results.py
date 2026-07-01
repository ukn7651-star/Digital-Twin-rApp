"""Result containers for the KPIs (per-UE and per-cell)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class UEKpi:
    ue_id: str
    serving_cell: str
    x: float
    y: float
    sinr_db: float
    mcs: int
    throughput_mbps: float


@dataclass
class CellKpi:
    cell_id: str
    num_attached: int
    throughput_mbps: float


@dataclass
class KpiResult:
    ues: list[UEKpi] = field(default_factory=list)
    cells: list[CellKpi] = field(default_factory=list)

    def ue_rows(self) -> list[dict]:
        return [asdict(u) for u in self.ues]

    def cell_rows(self) -> list[dict]:
        return [asdict(c) for c in self.cells]

    def to_dict(self) -> dict:
        return {"ues": self.ue_rows(), "cells": self.cell_rows()}
