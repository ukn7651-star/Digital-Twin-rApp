"""Experiment harness: sweep scenes x seeds x configs and aggregate statistics.

Produces the statistical results for the paper: multiple urban scenes, multiple
random network layouts (seeds) per scene, and an inter-cell-load configuration
sweep, with robust aggregates (means, medians, and *outage rates*, since random
urban layouts put some UEs out of coverage). Each scene's OpenStreetMap geometry
is fetched and built once, then reused across all seeds (only the random network
placement and the ray tracing re-run per seed), so Overpass is hit once per scene.

Run:  CUDA_VISIBLE_DEVICES="" python3 -m dtrapp.runner.sweep --seeds 8 --out experiments/results
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from dtrapp.config import BoundingBox, SimulationConfig
from dtrapp.geometry import build_scene
from dtrapp.geometry import overpass as ov
from dtrapp.kpi import compute_kpis
from dtrapp.network import RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.rapp import kpi_metrics, run_traffic_steering

SCENES = {
    "berlin_mitte": BoundingBox(52.5132, 13.3750, 52.5168, 13.3810),
    "paris_opera": BoundingBox(48.8700, 2.3300, 48.8730, 2.3350),
    "manhattan_mid": BoundingBox(40.7520, -73.9870, 40.7550, -73.9820),
}
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
LOAD_SWEEP = [0.0, 0.25, 0.5, 0.75, 1.0]


def _extent_from_ground(scene_dir: Path):
    """Scene extent recovered from the built ground plane (no OSM fetch)."""
    lines = (scene_dir / "meshes" / "ground.ply").read_text().splitlines()
    i = lines.index("end_header") + 1
    v = [list(map(float, lines[i + k].split()))[:2] for k in range(4)]
    xs = [a for a, _ in v]
    ys = [b for _, b in v]
    return (min(xs), min(ys), max(xs), max(ys))


def _scene_artifacts(name: str, bbox: BoundingBox, cfg: SimulationConfig, scene_dir: Path):
    """Reuse a built scene if present; only hit Overpass when we must.

    Geometry does not depend on any radio parameter, so rebuilding it on every run only
    adds a network dependency (and Overpass rate-limits and times out).
    """
    from dtrapp.geometry.scene_builder import SceneArtifacts

    if (scene_dir / "scene.xml").exists() and (scene_dir / "meshes" / "ground.ply").exists():
        n = len(list((scene_dir / "meshes").glob("bldg-*.ply")))
        print(f"[{name}] reusing built scene ({scene_dir})")
        return SceneArtifacts(scene_dir / "scene.xml", None, n, _extent_from_ground(scene_dir))
    print(f"[{name}] fetching OSM + building scene once ...")
    return build_scene(bbox, scene_dir, cfg, overpass_json=fetch_osm(bbox, cfg))


def base_config(bbox: BoundingBox) -> SimulationConfig:
    return SimulationConfig(
        bbox=bbox, default_building_height_m=15.0,
        num_sites=3, sectors_per_site=3, bs_height_m=25.0,
        tx_power_dbm=46.0, carrier_freq_hz=3.5e9, bandwidth_hz=38.16e6,
        num_ues=30, ue_height_m=1.5, ue_noise_figure_db=7.0, max_depth=3,
        bs_antenna_rows=4, bs_antenna_cols=1,
        subcarrier_spacing_hz=30e3, num_subcarriers=1272, num_ofdm_symbols=12,
        temperature_k=290.0, bler_target=0.1, mcs_table_index=1,
        neighbor_load=1.0, eesm_beta_scale=1.0,
    )


def fetch_osm(bbox: BoundingBox, cfg: SimulationConfig) -> dict:
    last = None
    for url in OVERPASS_URLS:
        try:
            return ov.fetch_overpass_json(bbox, replace(cfg, overpass_url=url, overpass_timeout_s=90))
        except Exception as e:
            last = e
            print(f"      overpass {url.split('//')[1].split('/')[0]} failed: {str(e)[:50]}")
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def _pct(new: float, old: float) -> float:
    return 100.0 * (new - old) / old if old > 0 else float("nan")


def _run_record(scene, seed, b, s):
    return {
        "scene": scene, "seed": seed,
        "base_mean": b["mean_mbps"], "base_median": b["median_mbps"],
        "base_edge": b["edge_mbps"], "base_served_edge": b["served_edge_mbps"],
        "base_outage": b["outage_frac"], "base_jain": b["jain"], "base_max_load": b["max_load"],
        "steer_mean": s["mean_mbps"], "steer_median": s["median_mbps"],
        "steer_edge": s["edge_mbps"], "steer_served_edge": s["served_edge_mbps"],
        "steer_outage": s["outage_frac"], "steer_jain": s["jain"], "steer_max_load": s["max_load"],
        "gain_mean_pct": _pct(s["mean_mbps"], b["mean_mbps"]),
        "gain_median_pct": _pct(s["median_mbps"], b["median_mbps"]),
        "gain_servededge_pct": _pct(s["served_edge_mbps"], b["served_edge_mbps"]),
        "gain_jain_pct": _pct(s["jain"], b["jain"]),
        "outage_delta": s["outage_frac"] - b["outage_frac"],
        "load_delta": s["max_load"] - b["max_load"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--scenes", default=",".join(SCENES))
    ap.add_argument("--out", default="experiments/results")
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    scene_names = [s for s in args.scenes.split(",") if s in SCENES]
    seeds = list(range(args.seeds))
    rows, load_rows, ue_tp = [], [], {}
    t0 = time.time()

    for scene in scene_names:
        bbox = SCENES[scene]; cfg = base_config(bbox)
        art = _scene_artifacts(scene, bbox, cfg, out / "scene" / scene)
        engine = SionnaPropagationEngine(art.scene_xml, cfg)
        print(f"      {art.num_buildings} buildings; {len(seeds)} seeds ...")
        ue_tp[scene] = {"baseline": [], "steered": []}
        cached = None
        for seed in seeds:
            cfg_s = replace(cfg, seed=seed)
            net = RandomNetworkSource(cfg_s, art.extent_m).generate()
            cfr = engine.compute_cfr(net)
            steer = run_traffic_steering(net, cfr, cfg_s)
            b, s = steer.baseline_metrics, steer.steered_metrics
            rows.append(_run_record(scene, seed, b, s))
            ue_tp[scene]["baseline"] += [u.throughput_mbps for u in steer.baseline.ues]
            ue_tp[scene]["steered"] += [u.throughput_mbps for u in steer.steered.ues]
            print(f"      seed {seed}: outage {b['outage_frac']*100:4.0f}% | "
                  f"median {b['median_mbps']:5.2f}->{s['median_mbps']:5.2f} | "
                  f"served-edge +{_pct(s['served_edge_mbps'], b['served_edge_mbps']):5.1f}% | "
                  f"peak load {b['max_load']:.0f}->{s['max_load']:.0f}")
            if cached is None:
                cached = (net, cfr)
        net_c, cfr_c = cached
        for load in LOAD_SWEEP:
            m = kpi_metrics(compute_kpis(net_c, cfr_c, replace(cfg, neighbor_load=load)))
            load_rows.append({"scene": scene, "neighbor_load": load, "mean_mbps": m["mean_mbps"],
                              "median_mbps": m["median_mbps"], "outage_frac": m["outage_frac"]})

    with open(out / "sweep_runs.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with open(out / "load_sweep.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(load_rows[0].keys())); w.writeheader(); w.writerows(load_rows)

    def stat(vals):
        v = np.array(vals, float); v = v[np.isfinite(v)]
        return {"mean": float(v.mean()) if v.size else float("nan"),
                "std": float(v.std()) if v.size else float("nan"), "n": int(v.size)}

    summary = {"num_seeds": len(seeds), "num_scenes": len(scene_names),
               "runtime_s": round(time.time() - t0, 1), "scenes": {}, "overall": {}, "pooled_cell_edge": {}}
    keys = ["base_outage", "steer_outage", "gain_mean_pct", "gain_median_pct",
            "gain_servededge_pct", "gain_jain_pct", "load_delta"]
    for scene in scene_names:
        sub = [r for r in rows if r["scene"] == scene]
        summary["scenes"][scene] = {k: stat([r[k] for r in sub]) for k in keys}
    for k in keys:
        summary["overall"][k] = stat([r[k] for r in rows])
    # pooled cell-edge (stable): 5th/10th percentile over all UEs, baseline vs steered
    ball = np.concatenate([np.array(ue_tp[s]["baseline"]) for s in scene_names])
    sall = np.concatenate([np.array(ue_tp[s]["steered"]) for s in scene_names])
    for p in (5, 10, 50):
        summary["pooled_cell_edge"][f"p{p}"] = {
            "baseline": float(np.percentile(ball, p)), "steered": float(np.percentile(sall, p))}
    summary["pooled_outage"] = {"baseline": float(np.mean(ball <= 0)), "steered": float(np.mean(sall <= 0))}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    _plots(out, rows, ue_tp, load_rows, scene_names)

    o = summary["overall"]
    print(f"\n=== SUMMARY ({len(rows)} runs over {len(scene_names)} scenes, "
          f"{summary['runtime_s']:.0f}s) ===")
    print(f"  mean outage: baseline {summary['pooled_outage']['baseline']*100:.1f}% -> "
          f"steered {summary['pooled_outage']['steered']*100:.1f}%")
    print(f"  median-throughput gain: {o['gain_median_pct']['mean']:.1f}% "
          f"(n={o['gain_median_pct']['n']})")
    print(f"  served cell-edge gain: {o['gain_servededge_pct']['mean']:.1f}% "
          f"(n={o['gain_servededge_pct']['n']}/{len(rows)} runs where edge>0)")
    print(f"  peak-load change: {o['load_delta']['mean']:.2f} UEs")
    pe = summary["pooled_cell_edge"]
    print(f"  pooled p10 throughput: {pe['p10']['baseline']:.2f} -> {pe['p10']['steered']:.2f} Mbps")
    print(f"wrote {out}/summary.json, sweep_runs.csv, load_sweep.csv, *.png")
    return 0


def _plots(out, rows, ue_tp, load_rows, scene_names):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    # Fig 1: pooled per-UE throughput CDF baseline vs steered
    fig, ax = plt.subplots(figsize=(6, 4))
    b = np.sort(np.concatenate([np.array(ue_tp[s]["baseline"]) for s in scene_names]))
    s = np.sort(np.concatenate([np.array(ue_tp[s]["steered"]) for s in scene_names]))
    ax.plot(b, np.linspace(0, 1, len(b)), label="baseline", lw=2)
    ax.plot(s, np.linspace(0, 1, len(s)), label="rApp", lw=2)
    ax.set_xlabel("per-UE throughput [Mbps]"); ax.set_ylabel("CDF")
    ax.set_title("Per-UE throughput, pooled over scenes/seeds")
    ax.grid(True, alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig(out / "fig_cdf_pooled.png", dpi=130); plt.close(fig)

    # Fig 2: outage rate vs inter-cell load, per scene
    fig, ax = plt.subplots(figsize=(6, 4))
    for scene in scene_names:
        pts = sorted((r["neighbor_load"], r["outage_frac"] * 100) for r in load_rows if r["scene"] == scene)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", label=scene)
    ax.set_xlabel("neighbour load factor"); ax.set_ylabel("UE outage rate [%]")
    ax.set_title("Coverage vs inter-cell load")
    ax.grid(True, alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig(out / "fig_outage_vs_load.png", dpi=130); plt.close(fig)

    # Fig 3: mean throughput vs inter-cell load, per scene
    fig, ax = plt.subplots(figsize=(6, 4))
    for scene in scene_names:
        pts = sorted((r["neighbor_load"], r["mean_mbps"]) for r in load_rows if r["scene"] == scene)
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="s", label=scene)
    ax.set_xlabel("neighbour load factor"); ax.set_ylabel("mean per-UE throughput [Mbps]")
    ax.set_title("Throughput vs inter-cell load")
    ax.grid(True, alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig(out / "fig_throughput_vs_load.png", dpi=130); plt.close(fig)

    # Fig 4: rApp gain by scene (mean +/- std over seeds), per headline metric
    metrics = [("gain_median_pct", "Median tput"),
               ("gain_servededge_pct", "Served edge"),
               ("gain_jain_pct", "Jain fairness")]

    def _ms(scene, col):
        v = np.array([r[col] for r in rows if r["scene"] == scene], float)
        v = v[np.isfinite(v)]
        return (float(v.mean()), float(v.std())) if v.size else (float("nan"), 0.0)

    x = np.arange(len(scene_names)); w = 0.26
    fig, ax = plt.subplots(figsize=(6, 4))
    for i, (col, lab) in enumerate(metrics):
        means = [_ms(s, col)[0] for s in scene_names]
        stds = [_ms(s, col)[1] for s in scene_names]
        ax.bar(x + (i - 1) * w, means, w, yerr=stds, capsize=3, label=lab)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x); ax.set_xticklabels(scene_names, rotation=0)
    ax.set_ylabel("rApp gain over strongest-cell [%]")
    ax.set_title(r"Traffic-steering gains by scene (mean $\pm$ std over seeds)")
    ax.grid(True, axis="y", alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig(out / "fig_gains_by_scene.png", dpi=130); plt.close(fig)

    # Fig 5: median gain vs baseline outage (what limits the gain)
    xo = np.array([r["base_outage"] * 100 for r in rows], float)
    yg = np.array([r["gain_median_pct"] for r in rows], float)
    m = np.isfinite(xo) & np.isfinite(yg); xo, yg = xo[m], yg[m]
    fig, ax = plt.subplots(figsize=(6, 4))
    for scene in scene_names:
        idx = [i for i, r in enumerate([r for r in rows]) if r["scene"] == scene]
        ax.scatter([xo[i] for i in idx], [yg[i] for i in idx], s=36,
                   edgecolor="k", lw=0.4, label=scene, zorder=3)
    if xo.size >= 3 and np.std(xo) > 0:
        rr = np.corrcoef(xo, yg)[0, 1]; b1, b0 = np.polyfit(xo, yg, 1)
        xx = np.linspace(xo.min(), xo.max(), 50)
        ax.plot(xx, b1 * xx + b0, "k--", lw=1.5, zorder=2,
                label=f"fit (r={rr:.2f}, $R^2$={rr*rr:.2f})")
    ax.axhline(0, color="0.7", lw=0.8, zorder=1)
    ax.set_xlabel("baseline outage rate [%]")
    ax.set_ylabel("rApp median throughput gain [%]")
    ax.set_title("rApp gain vs baseline outage")
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / "fig_scatter_gain.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
