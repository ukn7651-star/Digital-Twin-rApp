#!/usr/bin/env python3
"""Single source of truth for the statistics quoted in the paper.

Reads only committed experiment outputs under ``experiments/results/`` and writes
``paper_stats.json``. Nothing here re-runs an experiment, so it is cheap to re-run
and the paper can be checked against it at any time.

What it adds over the raw summaries: bootstrap 95% confidence intervals, paired
significance tests (Wilcoxon signed-rank on absolute throughput, sign test on the
per-run gains), and correlations reported *within* scene as well as pooled --
because a pooled correlation across three cities can be produced entirely by the
between-city contrast, and reversed within every one of them.

Run:  python3 experiments/paper_stats.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.stats import (  # noqa: E402
    bootstrap_ci,
    mean_std,
    paired_sign_test_positive,
    paired_wilcoxon,
    pearson_r,
    summarize_gain,
    write_json,
)

RESULTS = ROOT / "experiments" / "results"


def _rows(name: str) -> list[dict]:
    with open(RESULTS / name) as fh:
        return list(csv.DictReader(fh))


def _json(name: str) -> dict | None:
    p = RESULTS / name
    return json.loads(p.read_text()) if p.exists() else None


def _f(rows, key):
    return [float(r[key]) for r in rows]


# --------------------------------------------------------------------------
def analyze_sweep(rows: list[dict]) -> dict:
    scenes = sorted({r["scene"] for r in rows})
    out = {"n_runs": len(rows), "n_scenes": len(scenes), "n_seeds": len(rows) // len(scenes)}

    out["gains_pct"] = {
        "median": summarize_gain(_f(rows, "gain_median_pct"), seed=1),
        "served_edge": summarize_gain(_f(rows, "gain_servededge_pct"), seed=2),
        "jain": summarize_gain(_f(rows, "gain_jain_pct"), seed=3),
        "mean": summarize_gain(_f(rows, "gain_mean_pct"), seed=4),
    }
    out["load_delta"] = {**mean_std(_f(rows, "load_delta")),
                         **bootstrap_ci(_f(rows, "load_delta"), seed=5)}

    # Paired tests on the absolute rates, not the derived percentages.
    out["paired_tests"] = {
        "median_mbps": paired_wilcoxon(_f(rows, "base_median"), _f(rows, "steer_median")),
        "served_edge_mbps": paired_wilcoxon(_f(rows, "base_served_edge"),
                                            _f(rows, "steer_served_edge")),
        "peak_load_ues": paired_wilcoxon(_f(rows, "base_max_load"), _f(rows, "steer_max_load")),
        "mean_mbps": paired_wilcoxon(_f(rows, "base_mean"), _f(rows, "steer_mean")),
        # Outage is bit-for-bit identical in every run, so the test is undefined --
        # which is a stronger statement than a large p-value, and we say so.
        "outage": paired_wilcoxon(_f(rows, "base_outage"), _f(rows, "steer_outage")),
    }
    out["outage"] = {
        "baseline_mean": float(np.mean(_f(rows, "base_outage"))),
        "steered_mean": float(np.mean(_f(rows, "steer_outage"))),
        "max_abs_delta": float(np.max(np.abs(_f(rows, "outage_delta")))),
    }

    # Correlations: pooled, and within each scene. A pooled r can be manufactured by
    # the between-city contrast alone (Simpson's paradox), so both are reported.
    gain = _f(rows, "gain_median_pct")
    outage = list(np.array(_f(rows, "base_outage")) * 100)
    load = _f(rows, "base_max_load")
    out["correlations"] = {
        "pooled": {"gain_vs_outage": pearson_r(outage, gain),
                   "gain_vs_peak_load": pearson_r(load, gain)},
        "within_scene": {
            s: {"gain_vs_outage": pearson_r(
                    [100 * float(r["base_outage"]) for r in rows if r["scene"] == s],
                    [float(r["gain_median_pct"]) for r in rows if r["scene"] == s]),
                "gain_vs_peak_load": pearson_r(
                    [float(r["base_max_load"]) for r in rows if r["scene"] == s],
                    [float(r["gain_median_pct"]) for r in rows if r["scene"] == s])}
            for s in scenes},
    }

    # Seeds within a scene share the same geometry, so the pooled n=24 test has a
    # cluster structure and overstates the effective sample size. Report the three
    # per-scene tests (8 independent layouts each) alongside the pooled one.
    out["paired_tests_by_scene"] = {
        s: {"median_mbps": paired_wilcoxon(
                [float(r["base_median"]) for r in rows if r["scene"] == s],
                [float(r["steer_median"]) for r in rows if r["scene"] == s]),
            "served_edge_mbps": paired_wilcoxon(
                [float(r["base_served_edge"]) for r in rows if r["scene"] == s],
                [float(r["steer_served_edge"]) for r in rows if r["scene"] == s])}
        for s in scenes}

    out["by_scene"] = {
        s: {"gain_median_pct": mean_std([float(r["gain_median_pct"]) for r in rows if r["scene"] == s]),
            "gain_servededge_pct": mean_std([float(r["gain_servededge_pct"]) for r in rows if r["scene"] == s]),
            "gain_jain_pct": mean_std([float(r["gain_jain_pct"]) for r in rows if r["scene"] == s]),
            "base_outage": mean_std([float(r["base_outage"]) for r in rows if r["scene"] == s]),
            "load_delta": mean_std([float(r["load_delta"]) for r in rows if r["scene"] == s]),
            "sign_median_gain": paired_sign_test_positive(
                [float(r["gain_median_pct"]) for r in rows if r["scene"] == s])}
        for s in scenes}
    return out


def analyze_decision_regret(rows: list[dict], summary: dict) -> dict:
    """Reporting error vs decision error (regret), per surrogate link curve."""
    out = {"fit": summary["fit"], "n_runs": summary["n_runs"], "curves": {}}
    for i, curve in enumerate(sorted({r["curve"] for r in rows})):
        sub = [r for r in rows if r["curve"] == curve]
        reg = _f(sub, "regret_utility_pts")
        infl = [float(r["tput_inflation_median_pct"]) for r in sub
                if np.isfinite(float(r["tput_inflation_median_pct"]))]
        out["curves"][curve] = {
            "reporting_error_pct": {**mean_std(infl), **bootstrap_ci(infl, seed=30 + i)},
            "regret_utility_nats": {**mean_std(reg), **bootstrap_ci(reg, seed=40 + i),
                                    "max": float(np.max(reg))},
            "frac_decisions_differ": float(np.mean([int(r["decisions_differ"]) for r in sub])),
            "mean_steer_jaccard": float(np.mean(_f(sub, "steer_jaccard"))),
        }
    return out


def analyze_l2s_fit() -> dict:
    """How closely does each surrogate reproduce the OAI curve's MCS thresholds?

    This is the mechanism behind "one scalar is enough": the OAI staircase is a
    Shannon-optimal staircase displaced by delta. The RMS threshold error says so; the
    max says where a surrogate fails (the attenuation model is good on average and bad
    at the extremes, which is exactly why it reports well and acts badly).
    """
    from dtrapp.kpi.link_curve import load_link_curve
    from experiments.decision_regret import surrogate_curves

    oai = load_link_curve()
    sur, fit = surrogate_curves(oai)
    ref = np.array([q["sinr_db"] for q in oai.points])
    out = {"fit": fit, "threshold_error_db": {}}
    for k, c in sur.items():
        e = np.array([q["sinr_db"] for q in c.points]) - ref
        out["threshold_error_db"][k] = {"rms": float(np.sqrt((e ** 2).mean())),
                                        "max_abs": float(np.abs(e).max())}
    return out


def analyze_real_gap() -> dict:
    data = _json("real_fidelity_gap.json")
    if data is None:
        return {}
    rows = _rows("real_fidelity_gap.csv")
    mv = [r for r in rows if int(r["moved"]) and not int(r["outage"])]
    out = {"abs_link_fidelity": data["abs_link_fidelity"],
           "n_moved_evaluated": data["n_moved_evaluated"]}
    if mv:
        vs_mac = _f(mv, "gap_vs_mac_pts")
        vs_app = _f(mv, "fidelity_gap_pts")
        out["gap_vs_mac_pts"] = {**mean_std(vs_mac), **bootstrap_ci(vs_mac, seed=50),
                                 "median": float(np.median(vs_mac))}
        out["gap_vs_app_pts"] = {**mean_std(vs_app), **bootstrap_ci(vs_app, seed=51),
                                 "median": float(np.median(vs_app))}
        # Does the CI for the twin-vs-MAC gap straddle zero? That is the claim.
        out["gap_vs_mac_ci_contains_zero"] = bool(
            out["gap_vs_mac_pts"]["ci_lo"] <= 0.0 <= out["gap_vs_mac_pts"]["ci_hi"])
        out["gap_vs_app_ci_contains_zero"] = bool(
            out["gap_vs_app_pts"]["ci_lo"] <= 0.0 <= out["gap_vs_app_pts"]["ci_hi"])
        out["twin_vs_mac_gain_correlation"] = pearson_r(_f(mv, "twin_gain_pct"),
                                                        _f(mv, "mac_gain_pct"))
        out["twin_vs_app_gain_correlation"] = pearson_r(_f(mv, "twin_gain_pct"),
                                                        _f(mv, "real_gain_pct"))
    return out


def analyze_null_control() -> dict:
    d = _json("multignb_null_control.json")
    return {} if d is None else {"arms": {k: {"naive": v["naive_apparent_gain_pct"],
                                              "balanced": v["balanced_apparent_gain_pct"],
                                              "mean_dl_mcs_pci0": v["mean_dl_mcs_pci0"],
                                              "mean_dl_mcs_pci1": v["mean_dl_mcs_pci1"]}
                                          for k, v in d["arms"].items()}}


# --------------------------------------------------------------------------
def main() -> int:
    stats: dict = {"sweep": analyze_sweep(_rows("sweep_runs.csv"))}

    dr = _json("decision_regret.json")
    if dr is not None:
        stats["decision_regret"] = analyze_decision_regret(_rows("decision_regret.csv"), dr)
    if (es := _json("eesm_sensitivity.json")) is not None:
        stats["eesm_sensitivity"] = es
    stats["l2s_fit"] = analyze_l2s_fit()
    stats["real_fidelity_gap"] = analyze_real_gap()
    stats["null_control"] = analyze_null_control()

    write_json(RESULTS / "paper_stats.json", stats)

    g = stats["sweep"]["gains_pct"]
    pt = stats["sweep"]["paired_tests"]
    print("=== PAPER STATS ===")
    for k in ("median", "served_edge", "jain"):
        v = g[k]
        print(f"  {k:<12} {v['mean']:+6.1f}%  95% CI [{v['ci_lo']:+.1f}, {v['ci_hi']:+.1f}]  "
              f"sign p={v['sign_p_value']:.2g}  "
              f"({v['sign_n_positive']}+/{v['sign_n_negative']}-/{v['sign_n_tied']} tied)")
    print(f"  Wilcoxon median Mbps p={pt['median_mbps']['p_value']:.2g}; "
          f"served-edge p={pt['served_edge_mbps']['p_value']:.2g}; "
          f"peak load p={pt['peak_load_ues']['p_value']:.2g}")
    print(f"  outage test: {pt['outage']['p_value']} (all 24 differences exactly zero)")
    print("  per-scene Wilcoxon (8 layouts each, clustered by geometry):")
    for sc, v in stats["sweep"]["paired_tests_by_scene"].items():
        print(f"    {sc:<15} median p={v['median_mbps']['p_value']:.4f}  "
              f"served-edge p={v['served_edge_mbps']['p_value']:.4f}")
    c = stats["sweep"]["correlations"]
    print(f"  gain~outage pooled r={c['pooled']['gain_vs_outage']['r']:+.2f}; "
          f"within-scene " + ", ".join(f"{s.split('_')[0]} {v['gain_vs_outage']['r']:+.2f}"
                                       for s, v in c["within_scene"].items()))
    print(f"  gain~peak-load pooled r={c['pooled']['gain_vs_peak_load']['r']:+.2f}; "
          f"within-scene " + ", ".join(f"{s.split('_')[0]} {v['gain_vs_peak_load']['r']:+.2f}"
                                       for s, v in c["within_scene"].items()))
    if "decision_regret" in stats:
        print("  regret [nats], 95% CI:")
        for k, v in stats["decision_regret"]["curves"].items():
            r = v["regret_utility_nats"]
            e = v["reporting_error_pct"]
            print(f"    {k:<11} report {e['mean']:+6.1f}% [{e['ci_lo']:+.1f},{e['ci_hi']:+.1f}]   "
                  f"regret {r['mean']:.3f} [{r['ci_lo']:.3f},{r['ci_hi']:.3f}]")
    te = stats["l2s_fit"]["threshold_error_db"]
    print("  MCS-threshold error vs the OAI curve [dB]:")
    for k, v in te.items():
        print(f"    {k:<11} rms {v['rms']:.2f}  max {v['max_abs']:.2f}")
    rg = stats["real_fidelity_gap"]
    if "gap_vs_mac_pts" in rg:
        m, a = rg["gap_vs_mac_pts"], rg["gap_vs_app_pts"]
        print(f"  gap vs MAC {m['mean']:+.2f} pts, 95% CI [{m['ci_lo']:+.2f}, {m['ci_hi']:+.2f}] "
              f"-> contains 0: {rg['gap_vs_mac_ci_contains_zero']}")
        print(f"  gap vs app {a['mean']:+.2f} pts, 95% CI [{a['ci_lo']:+.2f}, {a['ci_hi']:+.2f}] "
              f"-> contains 0: {rg['gap_vs_app_ci_contains_zero']}")
    print(f"wrote {RESULTS/'paper_stats.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
