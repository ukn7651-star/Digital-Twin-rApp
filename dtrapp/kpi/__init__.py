"""Stages 4-5 - KPI: multi-cell SINR and SINR -> downlink throughput.

SINR includes inter-cell interference (not just thermal noise). Throughput uses
Shannon capacity with per-cell resource sharing among attached UEs. The mapping
from SINR to Mbps is our code; Sionna provides only the channel/path gain.
"""

from dtrapp.kpi.engine import compute_kpis
from dtrapp.kpi.results import CellKpi, SnapshotKpi, UEKpi
from dtrapp.kpi.sinr import (
    associate_cells,
    compute_received_power_dbm,
    compute_sinr_db,
    thermal_noise_dbm,
)
from dtrapp.kpi.throughput import shannon_throughput

__all__ = [
    "compute_kpis",
    "UEKpi",
    "CellKpi",
    "SnapshotKpi",
    "associate_cells",
    "compute_received_power_dbm",
    "compute_sinr_db",
    "thermal_noise_dbm",
    "shannon_throughput",
]
