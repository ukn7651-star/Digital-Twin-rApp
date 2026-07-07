"""Traffic-steering / load-balancing rApp on the digital twin (closed loop).

This is a non-real-time O-RAN rApp use case: when some cells are congested while
neighbours are lightly loaded, cell-edge users can be steered to the lighter cell
by raising that cell's **cell-individual offset (CIO)**, which biases association
(a UE attaches to the cell maximising ``RSRP + CIO``). The physical channel is
unchanged; only *which* cell serves each user moves. This is exactly the O1-level
knob commercial traffic-steering rApps use.

The controller runs a closed loop entirely on the twin:

    1. read KPIs (per-UE throughput, per-cell load) from the engine,
    2. propose a one-cell CIO change,
    3. re-evaluate KPIs on the twin,
    4. keep the change if it raises the proportional-fair utility,
    5. repeat until no single move helps.

Utility is the sum of log-throughput (proportional fairness): maximising it
balances load and lifts the cell-edge users a plain strongest-cell association
starves, without collapsing sum throughput. Every KPI evaluation reuses
``dtrapp.kpi.compute_kpis`` with a ``cio_db`` vector, so the control loop rides
on the exact same twin used for the baseline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.kpi.engine import compute_kpis
from dtrapp.kpi.link_curve import LinkCurve, load_link_curve
from dtrapp.kpi.results import KpiResult
from dtrapp.network.models import Network

_TP_FLOOR_MBPS = 1e-3  # throughput floor so a starved UE has finite (very low) log-utility


def kpi_metrics(result: KpiResult) -> dict:
    """Scalar summary of a KPI snapshot used to score control actions."""
    tp = np.array([u.throughput_mbps for u in result.ues], dtype=float)
    loads = np.array([c.num_attached for c in result.cells], dtype=float)
    if tp.size == 0:
        return {"sum_mbps": 0.0, "mean_mbps": 0.0, "edge_mbps": 0.0,
                "min_mbps": 0.0, "jain": 0.0, "max_load": 0.0, "utility": 0.0}
    tp_floored = np.maximum(tp, _TP_FLOOR_MBPS)
    served = tp[tp > 0.0]
    return {
        "sum_mbps": float(tp.sum()),
        "mean_mbps": float(tp.mean()),
        "median_mbps": float(np.median(tp)),
        "edge_mbps": float(np.percentile(tp, 5)),   # cell-edge (5th pct), incl. outage
        "served_edge_mbps": float(np.percentile(served, 5)) if served.size else 0.0,
        "min_mbps": float(tp.min()),
        "outage_frac": float(np.mean(tp <= 0.0)),   # fraction of UEs with no service
        "jain": float(tp.sum() ** 2 / (tp.size * np.sum(tp ** 2) + 1e-30)),
        "max_load": float(loads.max()) if loads.size else 0.0,
        "utility": float(np.log(tp_floored).sum()),  # proportional-fair objective
    }


@dataclass
class SteeringResult:
    """Outcome of the traffic-steering rApp loop."""

    baseline: KpiResult
    steered: KpiResult
    cio_db: np.ndarray
    baseline_metrics: dict
    steered_metrics: dict
    history: list[dict] = field(default_factory=list)

    def gains_pct(self) -> dict:
        """Percentage change (steered vs baseline) for the headline metrics."""
        out = {}
        for k in ("sum_mbps", "mean_mbps", "edge_mbps", "min_mbps", "jain"):
            b = self.baseline_metrics[k]
            out[k] = float(100.0 * (self.steered_metrics[k] - b) / b) if b > 0 else float("nan")
        out["max_load_delta"] = float(
            self.steered_metrics["max_load"] - self.baseline_metrics["max_load"]
        )
        return out


def association_changes(baseline: KpiResult, steered: KpiResult) -> list[dict]:
    """UEs whose serving cell changed between two KPI snapshots.

    Turns a steering decision (baseline vs steered association) into concrete
    per-UE handovers ``{ue_id, from_cell, to_cell}`` that a real stack would
    execute (e.g. via OAI telnet F1/N2 handover triggers).
    """
    base = {u.ue_id: u.serving_cell for u in baseline.ues}
    return [
        {"ue_id": u.ue_id, "from_cell": base[u.ue_id], "to_cell": u.serving_cell}
        for u in steered.ues
        if base.get(u.ue_id) is not None and base[u.ue_id] != u.serving_cell
    ]


def run_traffic_steering(
    network: Network,
    cfr,
    config: SimulationConfig,
    link_curve: LinkCurve | None = None,
    step_db: float = 1.0,
    cio_cap_db: float = 12.0,
    max_iters: int = 20,
    eps: float = 1e-6,
) -> SteeringResult:
    """Proportional-fair traffic steering via per-cell CIO (coordinate ascent).

    The utility surface over CIO is piecewise-constant - it only changes when a
    control offset grows large enough to flip a UE's serving cell - so a fixed
    small +/- step gets stuck on plateaus. Instead we do coordinate ascent with a
    per-cell **line search**: for each cell in turn, scan its CIO over a grid
    (holding the others fixed) and keep the value maximising the sum-log-throughput
    utility. Sweeps repeat until no cell's line search improves utility. Raising a
    cell's CIO pulls boundary UEs in (absorbing load); lowering it pushes UEs to
    neighbours (shedding load), so a single knob per cell covers both directions.
    Monotonically non-decreasing in utility by construction.
    """
    curve = link_curve if link_curve is not None else load_link_curve()
    num_cells = len(network.cells)
    grid = np.arange(-cio_cap_db, cio_cap_db + step_db / 2, step_db)

    def evaluate(cio):
        return compute_kpis(network, cfr, config, link_curve=curve, cio_db=cio)

    cio = np.zeros(num_cells, dtype=float)
    baseline = evaluate(cio)
    base_metrics = kpi_metrics(baseline)

    best, best_metrics, best_u = baseline, base_metrics, base_metrics["utility"]
    history = [{"iter": 0, "moved_cell": -1, "cio_db": 0.0, **base_metrics}]

    it = 0
    for _sweep in range(max_iters):
        improved = False
        for c in range(num_cells):
            local_best = None  # (utility, value, result, metrics)
            for val in grid:
                if float(val) == cio[c]:
                    continue
                trial = cio.copy()
                trial[c] = float(val)
                r = evaluate(trial)
                m = kpi_metrics(r)
                if m["utility"] > best_u + eps and (
                    local_best is None or m["utility"] > local_best[0]
                ):
                    local_best = (m["utility"], float(val), r, m)
            if local_best is not None:
                best_u, cio[c], best, best_metrics = (
                    local_best[0], local_best[1], local_best[2], local_best[3],
                )
                it += 1
                improved = True
                history.append(
                    {"iter": it, "moved_cell": c, "cio_db": cio[c], **best_metrics}
                )
        if not improved:
            break  # local optimum: no cell's line search improves utility

    return SteeringResult(
        baseline=baseline,
        steered=best,
        cio_db=cio,
        baseline_metrics=base_metrics,
        steered_metrics=best_metrics,
        history=history,
    )
