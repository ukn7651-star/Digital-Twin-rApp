"""Run the traffic-steering rApp closed loop on an exported ray-traced channel.

Consumes the twin's exported channel (``output/channel/cfr.npy`` + ``network.json``
from ``dtrapp.runner.cli``), runs the load-balancing rApp on it, and writes a
result summary (and plots, if matplotlib is available).

Usage:
    python3 -m dtrapp.runner.rapp_cli [channel_dir] [--config config.yaml] [--out output]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.network.models import Cell, Network, UE
from dtrapp.rapp import run_traffic_steering


def load_network(network_json: Path) -> Network:
    net = json.loads(network_json.read_text())
    cells = [
        Cell(
            cell_id=c["cell_id"],
            position=tuple(c["position"]),
            azimuth_deg=c["azimuth_deg"],
            tx_power_dbm=c["tx_power_dbm"],
            carrier_freq_hz=c["carrier_freq_hz"],
            bandwidth_hz=c["bandwidth_hz"],
        )
        for c in net["cells"]
    ]
    ues = [
        UE(
            ue_id=u["ue_id"],
            position=tuple(u["position"]),
            traffic_demand_mbps=u.get("traffic_demand_mbps", 0.0),
            noise_figure_db=u.get("noise_figure_db", 7.0),
        )
        for u in net["ues"]
    ]
    return Network(cells, ues)


def _load_config(path: str | None) -> SimulationConfig:
    if path and Path(path).exists():
        return SimulationConfig.from_yaml(path)
    # Engine-only defaults (bbox is unused by the KPI/rApp stages).
    return SimulationConfig(bbox=BoundingBox(0.0, 0.0, 0.01, 0.01))


def _save_plots(out: "SteeringResult", out_dir: Path) -> list[Path]:  # noqa: F821
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    saved = []
    base_tp = np.sort([u.throughput_mbps for u in out.baseline.ues])
    steer_tp = np.sort([u.throughput_mbps for u in out.steered.ues])
    cdf = np.linspace(0, 1, len(base_tp))

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(base_tp, cdf, label="baseline (strongest-cell)", lw=2)
    ax.plot(steer_tp, cdf, label="traffic-steering rApp", lw=2)
    ax.set_xlabel("per-UE downlink throughput [Mbps]")
    ax.set_ylabel("CDF")
    ax.set_title("Per-UE throughput: baseline vs rApp")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    p = out_dir / "rapp_throughput_cdf.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    saved.append(p)

    iters = [h["iter"] for h in out.history]
    util = [h["utility"] for h in out.history]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(iters, util, marker="o", lw=2)
    ax.set_xlabel("rApp control iteration")
    ax.set_ylabel("proportional-fair utility (sum log-throughput)")
    ax.set_title("rApp closed-loop convergence")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p = out_dir / "rapp_utility_convergence.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    saved.append(p)
    return saved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel_dir", nargs="?", default="output/channel",
                    help="dir with cfr.npy and network.json")
    ap.add_argument("--config", default="configs/example.yaml")
    ap.add_argument("--out", default="output")
    ap.add_argument("--step-db", type=float, default=1.0)
    args = ap.parse_args()

    d = Path(args.channel_dir)
    cfr = np.load(d / "cfr.npy")
    network = load_network(d / "network.json")
    config = _load_config(args.config)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loaded channel {cfr.shape}: {len(network.cells)} cells, {len(network.ues)} UEs")
    print("Running traffic-steering rApp (proportional-fair CIO hill-climb) ...")
    out = run_traffic_steering(network, cfr, config, step_db=args.step_db)

    b, s = out.baseline_metrics, out.steered_metrics
    gains = out.gains_pct()
    print(f"  iterations: {len(out.history) - 1}   moves applied")
    print(f"  {'metric':<14}{'baseline':>12}{'steered':>12}{'gain %':>10}")
    for k, unit in (("sum_mbps", "Mbps"), ("mean_mbps", "Mbps"),
                    ("edge_mbps", "Mbps"), ("min_mbps", "Mbps"), ("jain", "")):
        g = gains.get(k, float("nan"))
        print(f"  {k:<14}{b[k]:>12.3f}{s[k]:>12.3f}{g:>10.1f}")
    print(f"  {'max_load':<14}{b['max_load']:>12.0f}{s['max_load']:>12.0f}"
          f"{gains['max_load_delta']:>10.0f}")

    summary = {
        "channel_shape": list(cfr.shape),
        "num_cells": len(network.cells),
        "num_ues": len(network.ues),
        "baseline": b,
        "steered": s,
        "gains_pct": gains,
        "final_cio_db": out.cio_db.tolist(),
        "history": out.history,
    }
    res_path = out_dir / "rapp_result.json"
    res_path.write_text(json.dumps(summary, indent=2))
    print(f"wrote {res_path}")
    for p in _save_plots(out, out_dir):
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
