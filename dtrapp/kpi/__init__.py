"""Stages 4-5 - KPI: full Sionna SYS link-level chain.

From the ray-traced channel (CFR): post-equalization SINR (RZF precoding + LMMSE
equalizer) with inter-cell interference, link adaptation over 5G-NR MCS tables
(`InnerLoopLinkAdaptation` + `PHYAbstraction`), and proportional-fair resource
sharing -> per-UE and per-cell downlink throughput.
"""

from dtrapp.kpi.engine import compute_kpis
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi
from dtrapp.kpi.sys_link import compute_link_level_kpis

__all__ = ["compute_kpis", "compute_link_level_kpis", "UEKpi", "CellKpi", "KpiResult"]
