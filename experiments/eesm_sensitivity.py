#!/usr/bin/env python3
"""How much do the rApp's conclusions depend on the EESM beta calibration?

The KPI engine compresses the per-RE SINR vector to one effective SINR with EESM,
whose ``beta`` is set per modulation order from the link-abstraction literature and
scaled by one free parameter, ``eesm_beta_scale``. That parameter is the twin's only
unfitted knob, so a reviewer is entitled to ask what happens if it is wrong.

We re-run the *identical* rApp on the OAI-grounded twin at beta_scale in {0.8, 1.0,
1.2} (+/-20% around the literature defaults), sharing the ray-traced channel across
variants, and report how far the rApp's gain and its steering decisions move relative
to beta_scale = 1.0. Regret is measured the same way as in ``decision_regret.py``:
plan on the perturbed twin, be evaluated on the nominal one.

Outputs: experiments/results/eesm_sensitivity.{csv,json}
Run:  CUDA_VISIBLE_DEVICES="" python3 experiments/eesm_sensitivity.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dtrapp.kpi.engine import ChannelCache, compute_kpis
from dtrapp.kpi.link_curve import load_link_curve
from dtrapp.network import RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.rapp import association_changes, kpi_metrics, run_traffic_steering
from dtrapp.runner.sweep import SCENES, base_config
from experiments.decision_regret import _extent
from experiments.stats import bootstrap_ci, mean_std, write_json

NOMINAL = 1.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-dir", default="experiments/results/scene")
    ap.add_argument("--scenes", default=",".join(SCENES))
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--scales", default="0.8,1.2")
    ap.add_argument("--out", default="experiments/results")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    oai = load_link_curve()
    scales = [float(x) for x in args.scales.split(",")]

    rows = []
    for scene_name in args.scenes.split(","):
        scene = ROOT / args.scene_dir / scene_name
        cfg = base_config(SCENES[scene_name])
        eng = SionnaPropagationEngine(str(scene / "scene.xml"), cfg)
        ext = _extent(scene)
        print(f"[{scene_name}] ...", flush=True)

        for seed in range(args.seeds):
            cfg_s = replace(cfg, seed=seed)
            net = RandomNetworkSource(cfg_s, ext).generate()
            cfr = eng.compute_cfr(net)                     # shared physics
            cache = ChannelCache(cfr)

            nom_cfg = replace(cfg_s, eesm_beta_scale=NOMINAL)
            r_nom = run_traffic_steering(net, cfr, nom_cfg, link_curve=oai)
            set_nom = {(c["ue_id"], c["to_cell"])
                       for c in association_changes(r_nom.baseline, r_nom.steered)}
            m_nom = kpi_metrics(r_nom.steered)
            base_nom = kpi_metrics(r_nom.baseline)

            def on_nominal(cio):
                return kpi_metrics(compute_kpis(net, cfr, nom_cfg, link_curve=oai,
                                                cio_db=cio, cache=cache))

            for sc in scales:
                cfg_b = replace(cfg_s, eesm_beta_scale=sc)
                r_b = run_traffic_steering(net, cfr, cfg_b, link_curve=oai)
                set_b = {(c["ue_id"], c["to_cell"])
                         for c in association_changes(r_b.baseline, r_b.steered)}
                union = set_nom | set_b
                # Plan on the perturbed twin, live in the nominal one.
                m_alt = on_nominal(r_b.cio_db)
                gain_nom = (100.0 * (m_nom["median_mbps"] - base_nom["median_mbps"])
                            / base_nom["median_mbps"]) if base_nom["median_mbps"] > 0 else float("nan")
                m_alt_gain = (100.0 * (m_alt["median_mbps"] - base_nom["median_mbps"])
                              / base_nom["median_mbps"]) if base_nom["median_mbps"] > 0 else float("nan")
                rows.append({
                    "scene": scene_name, "seed": seed, "beta_scale": sc,
                    "decisions_differ": int(set_nom != set_b),
                    "steer_jaccard": (len(set_nom & set_b) / len(union)) if union else 1.0,
                    "regret_utility_pts": float(m_nom["utility"] - m_alt["utility"]),
                    "gain_nominal_pct": round(gain_nom, 4),
                    "gain_delivered_pct": round(m_alt_gain, 4),
                    "sinr_shift_db": round(float(np.mean(
                        [u.sinr_db for u in r_b.baseline.ues if u.sinr_db > -100])
                        - np.mean([u.sinr_db for u in r_nom.baseline.ues if u.sinr_db > -100])), 4),
                })
                print(f"  {scene_name} seed {seed} beta={sc}: differ={rows[-1]['decisions_differ']} "
                      f"J={rows[-1]['steer_jaccard']:.2f} "
                      f"regret={rows[-1]['regret_utility_pts']:+.3f} "
                      f"dSINR={rows[-1]['sinr_shift_db']:+.2f} dB", flush=True)

    with open(out / "eesm_sensitivity.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {"n_runs_per_scale": len(rows) // len(scales), "nominal_beta_scale": NOMINAL,
               "note": "regret = PF utility lost by planning on a twin whose EESM beta is "
                       "mis-scaled and being evaluated on the nominal twin; compare against "
                       "the link-curve regrets in decision_regret.json",
               "scales": {}}
    for sc in scales:
        sub = [r for r in rows if r["beta_scale"] == sc]
        reg = [r["regret_utility_pts"] for r in sub]
        summary["scales"][str(sc)] = {
            "frac_decisions_differ": float(np.mean([r["decisions_differ"] for r in sub])),
            "mean_steer_jaccard": float(np.mean([r["steer_jaccard"] for r in sub])),
            "regret_utility_nats": {**mean_std(reg), **bootstrap_ci(reg, seed=int(sc * 100))},
            "mean_sinr_shift_db": float(np.mean([r["sinr_shift_db"] for r in sub])),
        }
    write_json(out / "eesm_sensitivity.json", summary)
    print("\n=== EESM BETA SENSITIVITY ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
