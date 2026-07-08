"""Fidelity-gap experiment: does the link-model choice change rApp evaluation?

Runs the *identical* traffic-steering rApp on two twins that differ ONLY in the
SINR->throughput curve:

  * OAI-grounded curve  Phi_OAI  (real nr_dlsim, with implementation loss)
  * idealized curve     Phi_ideal (same MCS/SE set, but thresholds at the
    Shannon-optimal SINR = 10*log10(2^SE - 1); i.e. no implementation loss)

Everything else (geometry, ray tracing, association, interference) is shared: the
CFR is computed once per layout and fed to both. We measure how the idealized
curve changes (a) absolute throughput, (b) the *predicted rApp gain*, and
(c) the actual steering *decisions* (per-cell CIO and the set of handed-over UEs).

Run:  CUDA_VISIBLE_DEVICES="" .venv/bin/python experiments/fidelity_gap.py
"""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtrapp.kpi.link_curve import LinkCurve, load_link_curve
from dtrapp.network import RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.rapp import association_changes, run_traffic_steering
from dtrapp.runner.sweep import SCENES, base_config

ROOT = Path(__file__).resolve().parents[1]
SCENE_DIR = ROOT / "experiments" / "results" / "scene"
SEEDS = 8


def extent_from_ground(scene: str):
    lines = (SCENE_DIR / scene / "meshes" / "ground.ply").read_text().splitlines()
    i = lines.index("end_header") + 1
    v = [list(map(float, lines[i + k].split()))[:2] for k in range(4)]
    xs = [a for a, b in v]; ys = [b for a, b in v]
    return (min(xs), min(ys), max(xs), max(ys))


def idealized_curve(oai: LinkCurve) -> LinkCurve:
    """Same (MCS, SE) set as the OAI curve, but with Shannon-optimal thresholds
    (the SINR at which an ideal receiver would already achieve that SE)."""
    pts = []
    for p in oai.points:
        se = float(p["se_bps_per_hz"])
        sinr_ideal = 10.0 * np.log10(max(2 ** se - 1.0, 1e-9))
        pts.append({"sinr_db": sinr_ideal, "mcs": int(p["mcs"]), "se_bps_per_hz": se})
    return LinkCurve({"source": "idealized (Shannon-optimal thresholds)",
                      "bler_target": oai.bler_target,
                      "mcs_table_index": oai.mcs_table_index, "points": pts})


def steer_set(res) -> set:
    """Set of (ue_id -> to_cell) handovers the rApp recommends vs baseline."""
    return {(c["ue_id"], c["to_cell"]) for c in association_changes(res.baseline, res.steered)}


def _summary_from_csv() -> int:
    """Recompute the summary from the committed per-run CSV (no ray tracing)."""
    out = ROOT / "experiments" / "results"
    with open(out / "fidelity_gap.csv") as fh:
        rows = [{k: v for k, v in r.items()} for r in csv.DictReader(fh)]
    for r in rows:
        for k in r:
            if k != "scene":
                r[k] = float(r[k])
    return _write_summary(rows, out)


def main() -> int:
    if "--from-csv" in sys.argv:
        return _summary_from_csv()

    oai = load_link_curve()
    ideal = idealized_curve(oai)
    assert oai.is_oai, "expected the OAI-measured curve to be present"

    rows = []
    for scene in SCENES:
        cfg = base_config(SCENES[scene])
        ext = extent_from_ground(scene)
        eng = SionnaPropagationEngine(str(SCENE_DIR / scene / "scene.xml"), cfg)
        print(f"[{scene}] ...")
        for seed in range(SEEDS):
            cfg_s = replace(cfg, seed=seed)
            net = RandomNetworkSource(cfg_s, ext).generate()
            cfr = eng.compute_cfr(net)  # shared physics; curve applied afterwards
            r_oai = run_traffic_steering(net, cfr, cfg_s, link_curve=oai)
            r_id = run_traffic_steering(net, cfr, cfg_s, link_curve=ideal)

            b_o, s_o = r_oai.baseline_metrics, r_oai.steered_metrics
            b_i, s_i = r_id.baseline_metrics, r_id.steered_metrics

            def g(m_b, m_s, k):
                return 100.0 * (m_s[k] - m_b[k]) / m_b[k] if m_b[k] > 0 else float("nan")

            set_o, set_i = steer_set(r_oai), steer_set(r_id)
            union = set_o | set_i
            jacc = (len(set_o & set_i) / len(union)) if union else 1.0
            cio_diff_cells = int(np.sum(np.abs(np.asarray(r_oai.cio_db) - np.asarray(r_id.cio_db)) > 0.5))

            rows.append({
                "scene": scene, "seed": seed,
                # absolute-throughput inflation from the idealized curve (baseline)
                "base_med_oai": b_o["median_mbps"], "base_med_ideal": b_i["median_mbps"],
                "tput_inflation_pct": g(b_o, b_i, "median_mbps"),
                "mean_inflation_pct": 100.0 * (b_i["mean_mbps"] - b_o["mean_mbps"]) / b_o["mean_mbps"],
                # predicted rApp median-gain under each twin, and the error
                "gain_oai_pct": g(b_o, s_o, "median_mbps"),
                "gain_ideal_pct": g(b_i, s_i, "median_mbps"),
                # decision divergence
                "n_steer_oai": len(set_o), "n_steer_ideal": len(set_i),
                "steer_jaccard": jacc, "cio_diff_cells": cio_diff_cells,
                "decisions_differ": int(set_o != set_i),
            })
            print(f"   seed {seed}: base med {b_o['median_mbps']:.2f}(oai) vs "
                  f"{b_i['median_mbps']:.2f}(ideal) | gain {rows[-1]['gain_oai_pct']:.1f}%%(oai) vs "
                  f"{rows[-1]['gain_ideal_pct']:.1f}%%(ideal) | steer J={jacc:.2f} "
                  f"cioΔ={cio_diff_cells} differ={rows[-1]['decisions_differ']}")

    out = ROOT / "experiments" / "results"
    with open(out / "fidelity_gap.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    return _write_summary(rows, out)


def _write_summary(rows: list[dict], out: Path) -> int:
    def col(k):
        return np.array([r[k] for r in rows], float)

    gain_err = col("gain_ideal_pct") - col("gain_oai_pct")
    summary = {
        "n_runs": len(rows),
        # ``tput_inflation_pct`` is the inflation of each run's *median* UE throughput;
        # report its mean AND its median across runs, so neither is mistaken for the other.
        "median_tput_inflation_mean_over_runs_pct": float(np.nanmean(col("tput_inflation_pct"))),
        "median_tput_inflation_median_over_runs_pct": float(np.nanmedian(col("tput_inflation_pct"))),
        "mean_tput_inflation_pct": float(np.nanmean(col("mean_inflation_pct"))),
        "gain_oai_mean_pct": float(np.nanmean(col("gain_oai_pct"))),
        "gain_ideal_mean_pct": float(np.nanmean(col("gain_ideal_pct"))),
        "gain_abs_error_mean_pts": float(np.nanmean(np.abs(gain_err))),
        "gain_abs_error_median_pts": float(np.nanmedian(np.abs(gain_err))),
        "runs_decisions_differ": int(col("decisions_differ").sum()),
        "frac_decisions_differ": float(col("decisions_differ").mean()),
        "mean_steer_jaccard": float(col("steer_jaccard").mean()),
        "mean_cio_diff_cells": float(col("cio_diff_cells").mean()),
    }
    (out / "fidelity_gap.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    print("\n=== FIDELITY-GAP SUMMARY (idealized vs OAI-grounded twin) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
