"""Stages 4-5 - KPI: multi-cell SINR and SINR -> downlink throughput.

SINR includes inter-cell interference (not just noise) and is computed from the
ray-traced path gains. The SINR -> throughput mapping uses Sionna SYS's
link-to-system abstraction (link adaptation + PHY abstraction over 5G-NR MCS
tables) with per-cell resource sharing.
"""

from dtrapp.kpi.engine import compute_kpis
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi

__all__ = ["compute_kpis", "UEKpi", "CellKpi", "KpiResult"]
