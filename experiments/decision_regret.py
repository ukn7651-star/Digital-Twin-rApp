#!/usr/bin/env python3
"""Does the link curve change the rApp's *decision quality*, not just its numbers?

``experiments/fidelity_gap.py`` compares the OAI-measured curve against a
Shannon-optimal staircase. A reviewer will object, correctly, that nobody builds a
system-level simulator on a Shannon-optimal staircase: real ones use an analytical
curve calibrated to a link-level simulator. So this script strengthens the test in
two ways.

1. **Stronger baselines.** Besides the Shannon-optimal staircase (``ideal``) we add
   three surrogates over the same (MCS, SE) set, so the ONLY difference between twins
   is the SINR at which each MCS becomes available:
     * ``margin2db`` -- Shannon thresholds + a round 2 dB implementation margin, what a
       link-budget abstraction assumes with no access to link-level data
     * ``offset``    -- SE = log2(1 + gamma/delta), delta fitted to the OAI curve
     * ``attenuated``-- SE = a * log2(1 + gamma), a fitted (3GPP TR 36.942 style)
   Comparing ``margin2db`` against ``offset`` isolates whether the *value* of the margin
   matters or merely its presence. It is the value: an assumed 2 dB margin halves the
   reporting error but barely dents the regret.

2. **Regret, not divergence.** Disagreeing on the CIO vector is only interesting if it
   costs something. We take the CIO the rApp selects on each surrogate twin, evaluate it
   on the OAI-grounded twin (the best available proxy for reality), and report the
   utility lost relative to the CIO the rApp would have selected had it planned there:

       regret = U(cio_OAI | OAI twin) - U(cio_surrogate | OAI twin)  >= 0

   a *difference* in the proportional-fair objective (nats), not a ratio, and >= 0 by
   construction because the OAI-planned CIO is a local optimum of that objective on that
   twin. This is what an operator actually pays: not "the twin reported the wrong number"
   but "the twin picked the wrong action". The median-throughput variant is also recorded
   and can go negative, because the rApp optimises utility, not the median.

Outputs: experiments/results/decision_regret.{csv,json}, paper/fig_decision_regret.pdf
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
from dtrapp.kpi.link_curve import LinkCurve, load_link_curve
from dtrapp.network import RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.rapp import association_changes, kpi_metrics, run_traffic_steering
from dtrapp.runner.sweep import SCENES, base_config


# A round 2 dB margin is what a link-budget-style abstraction would assume without
# access to link-level data; the fitted value is 4.71 dB.
MARGIN_DB = 2.0


def _extent(scene_dir: Path):
    lines = (scene_dir / "meshes" / "ground.ply").read_text().splitlines()
    i = lines.index("end_header") + 1
    v = [list(map(float, lines[i + k].split()))[:2] for k in range(4)]
    xs = [a for a, _ in v]
    ys = [b for _, b in v]
    return (min(xs), min(ys), max(xs), max(ys))


def _curve(name: str, oai: LinkCurve, points) -> LinkCurve:
    return LinkCurve({"source": name, "bler_target": oai.bler_target,
                      "mcs_table_index": oai.mcs_table_index, "points": points})


def surrogate_curves(oai: LinkCurve) -> dict[str, LinkCurve]:
    """Alternative L2S curves over the identical (MCS, SE) set.

    Each assigns a different *required SINR* to each MCS. ``ideal`` is the
    Shannon-optimal threshold (no implementation loss). ``offset`` and ``attenuated``
    are the one-parameter analytical models a practitioner would calibrate to the
    link-level data, fitted here by least squares in dB against the OAI curve.
    """
    se = np.array([p["se_bps_per_hz"] for p in oai.points])
    sinr = np.array([p["sinr_db"] for p in oai.points])
    mcs = [int(p["mcs"]) for p in oai.points]
    gam = 10.0 ** (sinr / 10.0)

    def pack(req_sinr_db):
        return [{"sinr_db": float(s), "mcs": m, "se_bps_per_hz": float(e)}
                for s, m, e in zip(req_sinr_db, mcs, se)]

    shannon_req = 10.0 * np.log10(np.maximum(2 ** se - 1.0, 1e-9))

    # offset model: SE = log2(1 + gamma/delta)  =>  required SINR = shannon_req + delta
    delta_db = float(np.mean(10.0 * np.log10(gam / (2 ** se - 1.0))))
    # attenuated model: SE = a*log2(1 + gamma)  =>  required SINR = 10log10(2^(SE/a) - 1)
    a = float(np.mean(se / np.log2(1 + gam)))
    atten_req = 10.0 * np.log10(np.maximum(2 ** (se / a) - 1.0, 1e-9))

    return {
        "ideal": _curve("idealized (Shannon-optimal thresholds)", oai, pack(shannon_req)),
        # A textbook link-budget abstraction: a round implementation margin, not a fitted
        # one. It isolates whether the *value* of delta matters or merely its presence.
        "margin2db": _curve("analytical, uniform 2 dB implementation margin", oai,
                            pack(shannon_req + MARGIN_DB)),
        "offset": _curve(f"analytical, fitted SINR offset {delta_db:.2f} dB", oai,
                         pack(shannon_req + delta_db)),
        "attenuated": _curve(f"analytical, fitted attenuation a={a:.3f}", oai,
                             pack(atten_req)),
    }, {"fitted_offset_db": delta_db, "fitted_alpha": a, "fixed_margin_db": MARGIN_DB}


def _regret(net, cfr, cfg, oai: LinkCurve, surrogate: LinkCurve,
            cio_ref, cio_alt, cache) -> dict:
    """Two distinct errors a surrogate twin can make.

    *Reporting* error: the surrogate's own predicted throughput, versus the
    OAI-grounded twin's, for the same network. This is what a twin gets wrong when you
    read a number off it.

    *Decision* (regret) error: take the CIO the rApp selected on the surrogate, evaluate
    it on the OAI-grounded twin, and compare against the CIO the rApp would have selected
    had it planned on the OAI twin. This is what a twin costs you when you act on it.

    A twin can be badly wrong on the first and perfectly right on the second -- which is
    exactly what we find for a calibrated analytical curve.
    """
    def m(cio, curve=oai):
        return kpi_metrics(compute_kpis(net, cfr, cfg, link_curve=curve, cio_db=cio,
                                        cache=cache))

    zero = np.zeros(len(net.cells))
    m_ref, m_alt, m_base = m(cio_ref), m(cio_alt), m(zero)
    own_sur, own_oai = m(zero, surrogate), m_base       # each twin's own baseline report

    def rel(k):
        # fraction of the achievable rApp improvement that planning on the surrogate discards
        gain_ref, gain_alt = m_ref[k] - m_base[k], m_alt[k] - m_base[k]
        return float(100.0 * (gain_ref - gain_alt) / gain_ref) if gain_ref > 1e-9 else float("nan")

    def infl(k):
        return (float(100.0 * (own_sur[k] - own_oai[k]) / own_oai[k])
                if own_oai[k] > 1e-9 else float("nan"))

    return {
        "regret_utility_pts": float(m_ref["utility"] - m_alt["utility"]),
        "regret_median_pct_of_gain": rel("median_mbps"),
        "regret_servededge_pct_of_gain": rel("served_edge_mbps"),
        # reporting error of the surrogate twin, independent of any control decision
        "tput_inflation_median_pct": infl("median_mbps"),
        "tput_inflation_mean_pct": infl("mean_mbps"),
        "median_ref_mbps": m_ref["median_mbps"], "median_alt_mbps": m_alt["median_mbps"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-dir", default="experiments/results/scene")
    ap.add_argument("--scenes", default=",".join(SCENES))
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--out", default="experiments/results")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    oai = load_link_curve()
    assert oai.is_oai, "expected the OAI-measured curve"
    surrogates, fit = surrogate_curves(oai)
    print(f"[fit] {fit}", flush=True)

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
            cfr = eng.compute_cfr(net)                   # shared physics across curves
            cache = ChannelCache(cfr)
            r_oai = run_traffic_steering(net, cfr, cfg_s, link_curve=oai)
            set_oai = {(c["ue_id"], c["to_cell"])
                       for c in association_changes(r_oai.baseline, r_oai.steered)}

            for name, curve in surrogates.items():
                r_s = run_traffic_steering(net, cfr, cfg_s, link_curve=curve)
                set_s = {(c["ue_id"], c["to_cell"])
                         for c in association_changes(r_s.baseline, r_s.steered)}
                union = set_oai | set_s
                reg = _regret(net, cfr, cfg_s, oai, curve, r_oai.cio_db,
                              r_s.cio_db, cache)
                rows.append({
                    "scene": scene_name, "seed": seed, "curve": name,
                    "decisions_differ": int(set_oai != set_s),
                    "steer_jaccard": (len(set_oai & set_s) / len(union)) if union else 1.0,
                    "cio_l1_db": float(np.abs(np.asarray(r_oai.cio_db)
                                              - np.asarray(r_s.cio_db)).sum()),
                    **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in reg.items()},
                })
                print(f"  {scene_name} seed {seed} {name:<11} "
                      f"differ={rows[-1]['decisions_differ']} "
                      f"J={rows[-1]['steer_jaccard']:.2f} "
                      f"infl={reg['tput_inflation_median_pct']:+6.1f}% "
                      f"utility_regret={reg['regret_utility_pts']:+.3f}", flush=True)

    with open(out / "decision_regret.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {"n_seeds": args.seeds, "scenes": args.scenes.split(","),
               "n_runs": len(rows) // len(surrogates), "fit": fit,
               "note": "regret = what the rApp loses by planning on the surrogate twin and "
                       "being evaluated on the OAI-grounded one. Utility is the "
                       "proportional-fair objective the rApp actually maximises; the median "
                       "regret can go negative because a surrogate's CIO occasionally lands on "
                       "a higher median at lower PF utility.",
               "curves": {}}
    for name in surrogates:
        sub = [r for r in rows if r["curve"] == name]
        med = np.array([r["regret_median_pct_of_gain"] for r in sub], float)
        med = med[~np.isnan(med)]
        u = np.array([r["regret_utility_pts"] for r in sub], float)
        infl = np.array([r["tput_inflation_median_pct"] for r in sub], float)
        infl = infl[~np.isnan(infl)]
        summary["curves"][name] = {
            "source": surrogates[name].source,
            "n_runs": len(sub),
            # reporting error
            "tput_inflation_median_pct_mean": float(infl.mean()) if infl.size else None,
            "tput_inflation_median_pct_median": float(np.median(infl)) if infl.size else None,
            # decision error
            "frac_decisions_differ": float(np.mean([r["decisions_differ"] for r in sub])),
            "mean_steer_jaccard": float(np.mean([r["steer_jaccard"] for r in sub])),
            "regret_utility_mean": float(u.mean()),
            "regret_utility_std": float(u.std(ddof=1)) if u.size > 1 else 0.0,
            "regret_utility_max": float(u.max()),
            "frac_runs_with_regret": float(np.mean(u > 1e-6)),
            "regret_median_pct_of_gain_median": float(np.median(med)) if med.size else None,
        }
    (out / "decision_regret.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    _make_figure(ROOT / "paper/fig_decision_regret.png", rows, summary)
    print("\n=== DECISION REGRET ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


def _make_figure(fig_path: Path, rows: list[dict], summary: dict) -> None:
    """Reporting error vs decision error, per surrogate twin."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    order = ["ideal", "margin2db", "offset", "attenuated"]
    labels = {"ideal": "Shannon\n(uncalibrated)",
              "margin2db": "Shannon $+2$ dB\n(assumed margin)",
              "offset": "Shannon $+\\delta$\n(fitted margin)",
              "attenuated": "$a\\cdot$Shannon\n(fitted atten.)"}
    order = [c for c in order if c in summary["curves"]]
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))

    infl = [[r["tput_inflation_median_pct"] for r in rows
             if r["curve"] == c and r["tput_inflation_median_pct"] == r["tput_inflation_median_pct"]]
            for c in order]
    ax[0].boxplot(infl, tick_labels=[labels[c] for c in order], showmeans=True)
    ax[0].axhline(0, color="k", lw=1)
    ax[0].set_ylabel("throughput reporting error [%]")
    ax[0].set_title("What the twin says")
    ax[0].grid(True, axis="y", alpha=0.3)

    reg = [[r["regret_utility_pts"] for r in rows if r["curve"] == c] for c in order]
    ax[1].boxplot(reg, tick_labels=[labels[c] for c in order], showmeans=True)
    ax[1].axhline(0, color="k", lw=1)
    ax[1].set_ylabel("PF utility regret [nats]")
    ax[1].set_title("What acting on it costs")
    ax[1].grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    print(f"wrote {fig_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
