"""High-level KPI engine: Network + ray-traced CFR -> KpiResult (stages 4-5).

Delegates to the Sionna SYS link-level chain (`compute_link_level_kpis`):
post-equalization SINR (RZF + LMMSE) with inter-cell interference, link
adaptation over 5G-NR MCS tables, and proportional-fair resource sharing.
"""

from __future__ import annotations

from dtrapp.config import SimulationConfig
from dtrapp.kpi.results import KpiResult
from dtrapp.kpi.sys_link import compute_link_level_kpis
from dtrapp.network.models import Network


def compute_kpis(network: Network, cfr, config: SimulationConfig) -> KpiResult:
    """Compute per-UE and per-cell KPIs from the ray-traced channel (CFR)."""
    return compute_link_level_kpis(network, cfr, config)
