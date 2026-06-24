"""Stages 4-5 - KPI: multi-cell SINR and SINR -> downlink throughput.

SINR includes inter-cell interference (not just noise). Throughput uses Shannon
capacity with per-cell resource sharing. The SINR->Mbps mapping is our code;
Sionna provides only the channel/path gain.
"""

from dtrapp.kpi.engine import compute_kpis
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi

__all__ = ["compute_kpis", "UEKpi", "CellKpi", "KpiResult"]
