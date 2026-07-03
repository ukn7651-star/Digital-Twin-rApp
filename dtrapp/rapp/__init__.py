"""O-RAN rApp layer: closed-loop control on the digital twin.

The twin (geometry + ray tracing + KPI engine) produces per-UE/per-cell KPIs;
an rApp reads them, decides a control action, applies it to the twin, and reads
the KPIs again. The first rApp is traffic steering / load balancing via per-cell
cell-individual offset (CIO), the standard O-RAN non-RT control knob.
"""

from dtrapp.rapp.traffic_steering import (
    SteeringResult,
    kpi_metrics,
    run_traffic_steering,
)

__all__ = ["SteeringResult", "kpi_metrics", "run_traffic_steering"]
