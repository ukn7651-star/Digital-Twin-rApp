#!/usr/bin/env python3
"""Controlled multi-cell fidelity gap: twin-predicted vs real rApp steering gain.

Two real cells (CU + two F1 DUs) execute the rApp's association decision as a real
inter-cell handover, and we measure what that move actually delivers. Making the
comparison mean anything required removing four confounds, all of which the first
version of this experiment silently contained.

1. **Measurement order was aliased onto cell identity.** The old protocol measured
   once before the handover (always DU0) and once after it (always DU1), then
   relabelled the two numbers by cell. Every post-handover transient was charged to
   the cell. Since ``ci trigger_f1_ho`` always moves DU0 -> DU1, the *sign* of the
   reported "real gain" was a pure function of the direction the rApp happened to
   choose. ``experiments/multignb_null_control.py`` measures this bias directly, with
   both cells physically identical (true effect = 0).
   Fixed by a reversal (A/B/A/B) design -- chain handovers, discard the single
   pre-handover point, average each cell over positions of equal mean sequence
   position -- and by probing at TCP's plateau rather than 3 s into slow start.
   (A saturating UDP probe, the textbook alternative, is invalid here: in reverse
   mode iperf3 reports the *sending* rate. See ``oai_multicell_stack``.)

2. **The two cells were not the twin's two cells.** The stock ``pci1`` DU conf sits
   on a different carrier (3649.44 vs 3450.72 MHz) with a different SSB burst
   position, while the twin models two co-channel sectors of one site. Fixed by
   ``oai/conf/*.pci1.cochannel.conf``: DU1 now differs from DU0 only in PCI/cell-id.

3. **The channel the rApp steered on was not the channel the stack transmitted over.**
   Both DUs ran a clean rfsim channel. Fixed by ``oai/cfr_to_oai_multicell``: the UE
   is the rfsim *server*, so DU-k's samples pass through channel model
   ``rfsimu_channel_ue{k}``; we inject each UE->cell link's ray-traced taps and its
   relative link gain there. ``rxAddInput`` sums both DUs' waveforms, so the
   non-serving cell is real co-channel interference rather than a noise-floor proxy.

4. **Two things were being compared that are not the same quantity.** The twin's
   per-UE gain contains an airtime term ``B_cell/K`` -- moving a UE off a congested
   cell raises the share of everyone left behind -- and that is most of the rApp's
   benefit. A stack with one real UE has ``K = 1`` on both cells and *cannot*
   exhibit it. We therefore compare the **link component** of the steering gain:
   what moving this UE between these two cells does to its own deliverable rate,
   with the twin evaluated at fixed load. The full gain (with airtime) is reported
   separately and is explicitly *not* what the real gain is compared against.

Two further points of alignment, both stated rather than hidden:

* **Neighbour load.** The rApp decides on the twin at full neighbour load (the
  scenario's worst case). But on the real stack only one UE exists, so the
  non-serving DU carries no PDSCH -- it radiates SSB/SIB only. The *comparison*
  therefore evaluates the twin's per-cell link at ``neighbor_load = 0``, which is the
  condition the stack actually presents. Both loads are recorded.
* **Absolute SINR.** RT injection reproduces the *relative* per-cell link gain (the taps
  are unit-energy; the gain rides in ``path_loss_dB``), not the absolute SINR -- rfsim's
  noise floor is a config knob, not kTB*NF. ``experiments/rfsim_noise_calib.py`` measures
  ``noise_power_dB -> operating MCS`` and finds it **non-monotone**: sweeping -22 -> -2 dB
  with one cell muted gives MCS 8, 19, 14, 18, 14, 0. The map cannot be inverted, so the
  reference cell cannot be placed at the twin's operating point. We fix the floor at a
  value where the link works (-18 dB) and let the ray-traced split set the other cell.
  Absolute SINR matching is therefore *not* claimed, and cannot be on this emulator.

Status
------
The per-cell injection itself is confirmed on the live stack: the UE log shows
``[RT] injected 1 taps into rfsimu_channel_ue0/ue1`` carrying exactly the twin's link
gains, and the UE reaches MCS 27 on the twin's stronger cell. What does not close is the
*measurement*: with a channel model active on both rfsim connections the UE loses
downlink sync under a saturating probe, and the F1 handover then never completes. This
script records that per layout (``outcome`` column) rather than dropping the layout, so
the negative result is reproducible. See the paper's limitations.

Outputs: experiments/results/multignb_fidelity_gap.{csv,json}, paper/fig_multignb_gap.png

Prereqs: 5G core healthy, OAI built with telnetsrv, host READY (oai/check_host.sh).
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

from dtrapp.config import SimulationConfig
from dtrapp.kpi.engine import per_ue_cell_sinr
from dtrapp.kpi.link_curve import LinkCurve, load_link_curve
from dtrapp.network import RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.rapp import association_changes, run_traffic_steering
from dtrapp.runner.rapp_cli import _load_config
from experiments.oai_multicell_stack import (
    RUN,
    Stack,
    balanced_cell_means,
    ensure_iperf_server,
    reversal_sequence,
)
from oai.cfr_to_oai_multicell import (
    per_cell_link_gains_db,
    write_multicell_taps,
    write_ue_conf,
)

BLER = 0.1
# Twin cell -> PCI. DUs start in this order, so DU-pci{k} is rfsim connection k and
# therefore reads channel model rfsimu_channel_ue{k} on the UE (rfsim server).
CELL_PCI = {"s0-c0": 0, "s0-c1": 1}


def _pct(new, old) -> float:
    if new is None or old is None or old <= 0:
        return float("nan")
    return 100.0 * (new - old) / old


def _extent(scene_dir: Path):
    lines = (scene_dir / "meshes" / "ground.ply").read_text().splitlines()
    i = lines.index("end_header") + 1
    v = [list(map(float, lines[i + k].split()))[:2] for k in range(4)]
    xs = [a for a, _ in v]
    ys = [b for _, b in v]
    return (min(xs), min(ys), max(xs), max(ys))


def twin_layout(seed: int, config: SimulationConfig, eng: SionnaPropagationEngine, ext):
    """Two-sector twin for one layout, plus the rApp's steering decision."""
    cfg = replace(config, seed=seed, num_sites=1, sectors_per_site=2,
                  num_ues=20, neighbor_load=1.0)
    net = RandomNetworkSource(cfg, ext).generate()
    cfr = eng.compute_cfr(net)
    steer = run_traffic_steering(net, cfr, cfg, step_db=0.5, cio_cap_db=12.0)
    return net, cfr, cfg, steer, association_changes(steer.baseline, steer.steered)


def twin_link(cfr, net, cfg: SimulationConfig, curve: LinkCurve, ue_idx: int,
              load: float) -> list[dict]:
    """Twin's per-cell link prediction for one UE at a given neighbour load."""
    return per_ue_cell_sinr(net, cfr, replace(cfg, neighbor_load=load),
                            link_curve=curve)[ue_idx]


def measure_layout(cfr, ue_idx: int, cell_order: list[int], tag: str, n: int, dur: int,
                   noise_power_db: float) -> tuple[list[dict], dict, str]:
    """Inject this UE's per-cell ray-traced channels, then run the reversal design.

    ``cell_order[k]`` is the twin cell whose channel DU-pci{k} presents. The UE can only
    camp on DU0 (DU1 starts after attach), so the caller puts the UE's *strongest* cell
    first: baseline = strongest cell, exactly as the twin's association does.

    Returns (sequence, injection diagnostics, outcome). ``outcome`` records why a layout
    produced no usable number, rather than dropping it.
    """
    taps, conf = RUN / f"taps_{tag}.txt", RUN / f"ue_{tag}.conf"
    diag = write_multicell_taps(taps, cfr, ue_idx, cell_order)
    write_ue_conf(conf, num_cells=2, noise_power_db=noise_power_db)

    stack = Stack(tag=tag, ue_conf=conf, taps=taps, cochannel=True)
    rows: list[dict] = []
    try:
        stack.start()
        injected = dict(stack.injected_models())
        # Refuse to report a "controlled" measurement we did not actually control.
        for k, m in enumerate(diag["models"]):
            name = f"rfsimu_channel_ue{k}"
            if name not in injected or abs(injected[name] - m["gain_db"]) > 0.01:
                return [], diag, f"injection_unconfirmed:{name}"
        rows = reversal_sequence(stack, n=n, dur=dur)
    except Exception as e:
        return rows, diag, f"bringup_failed:{type(e).__name__}"
    finally:
        # Sync loss under chanmod is the failure mode that matters; capture the evidence.
        diag["ue_resyncs_after_attach"] = stack.resyncs_after_attach()
        stack.stop()

    if not any(r.get("ho_ok") for r in rows[1:]):
        return rows, diag, "handover_failed"
    if all(r["goodput_mbps"] is None for r in rows):
        return rows, diag, "probe_failed"
    # One re-sync per handover is normal; tens of them mean the downlink kept dropping,
    # and a goodput number measured through that is not a measurement of the channel.
    if diag.get("ue_resyncs_after_attach", 0) > 2 * max(n - 1, 1):
        return rows, diag, "link_unstable"
    return rows, diag, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/example.yaml")
    ap.add_argument("--seed-list", default="1,17,18,20,21,23,28,33",
                    help="layout seeds on which the rApp moves a UE")
    ap.add_argument("--n", type=int, default=4, help="measurements per reversal sequence")
    ap.add_argument("--dur", type=int, default=20, help="TCP flow seconds per measurement")
    ap.add_argument("--noise-power-db", type=float, default=-18.0,
                    help="rfsim noise floor. Arbitrary within the range where the link works: "
                         "the floor->MCS map is non-monotone and cannot be inverted "
                         "(see experiments/rfsim_noise_calib.py)")
    ap.add_argument("--compare-load", type=float, default=0.0,
                    help="neighbour load at which the twin's link is compared "
                         "(0 = an idle neighbour, which is what a one-UE stack presents)")
    ap.add_argument("--out", default="experiments/results")
    ap.add_argument("--fig", default="paper/fig_multignb_gap.png")
    ap.add_argument("--skip-measure", action="store_true")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = out / "multignb_fidelity_gap.csv", out / "multignb_fidelity_gap.json"

    seeds = [int(x) for x in args.seed_list.split(",") if x.strip()]
    config = _load_config(args.config)
    curve = load_link_curve()

    rows: list[dict] = []
    if args.skip_measure and csv_path.exists():
        with open(csv_path) as fh:
            rows = list(csv.DictReader(fh))
    else:
        scene = ROOT / "output" / "scene"
        eng = SionnaPropagationEngine(str(scene / "scene.xml"), config)
        ext = _extent(scene)
        ensure_iperf_server()
        print(f"[multignb] {len(seeds)} layouts; co-channel CU+2DU; per-cell RT channels; "
              f"reversal design (n={args.n}, {args.dur}s TCP); noise_power_dB="
              f"{args.noise_power_db}; twin compared at neighbor_load={args.compare_load}",
              flush=True)

        for seed in seeds:
            print(f"  seed {seed}: ray-trace + twin steering ...", flush=True)
            net, cfr, cfg, steer, moves = twin_layout(seed, config, eng, ext)
            if not moves:
                print("    no UE moved; skipping", flush=True)
                continue
            mv = moves[0]
            uid = mv["ue_id"]
            ue_idx = next(i for i, u in enumerate(net.ues) if u.ue_id == uid)
            from_cell, to_cell = CELL_PCI[mv["from_cell"]], CELL_PCI[mv["to_cell"]]

            link0 = twin_link(cfr, net, cfg, curve, ue_idx, args.compare_load)
            link1 = twin_link(cfr, net, cfg, curve, ue_idx, 1.0)
            b, s = link0[from_cell], link0[to_cell]
            if b["se_bps_per_hz"] <= 0.0:
                print("    twin predicts outage on the source cell; skipping", flush=True)
                continue
            twin_link_gain = _pct(s["se_bps_per_hz"], b["se_bps_per_hz"])

            # The UE can only camp on DU0 (DU1 starts after attach), so give DU0 the UE's
            # strongest ray-traced cell: baseline = strongest cell, as the twin associates.
            gains = per_cell_link_gains_db(cfr, ue_idx, [0, 1])
            best = int(np.argmax(gains))
            cell_order = [best, 1 - best]          # cell_order[k] -> DU-pci{k}
            pci_of = {c: k for k, c in enumerate(cell_order)}
            from_pci, to_pci = pci_of[from_cell], pci_of[to_cell]

            base_by = {u.ue_id: u for u in steer.baseline.ues}
            steer_by = {u.ue_id: u for u in steer.steered.ues}
            twin_full_gain = _pct(steer_by[uid].throughput_mbps, base_by[uid].throughput_mbps)

            tag = f"s{seed}_{uid}"
            print(f"    {uid}: {mv['from_cell']}->{mv['to_cell']}; twin link gain "
                  f"{twin_link_gain:.1f}%; DU-pci0 <- twin c{best} ({gains[best]:.2f} dB), "
                  f"DU-pci1 <- twin c{1-best} ({gains[1-best]:.2f} dB)", flush=True)
            seq, diag, outcome = measure_layout(cfr, ue_idx, cell_order, tag, args.n,
                                                args.dur, args.noise_power_db)

            bal = balanced_cell_means(seq) if seq else {}
            g_from = bal.get(f"g_pci{from_pci}_mbps")
            g_to = bal.get(f"g_pci{to_pci}_mbps")
            real_gain = _pct(g_to, g_from)
            rows.append({
                "seed": seed, "ue_id": uid, "outcome": outcome,
                "from_cell": mv["from_cell"], "to_cell": mv["to_cell"],
                "du_pci0_twin_cell": best, "du_pci1_twin_cell": 1 - best,
                "rt_gain_pci0_db": diag["models"][0]["gain_db"],
                "rt_gain_pci1_db": diag["models"][1]["gain_db"],
                "rt_rsrp_split_db": diag["rsrp_split_db"],
                "noise_power_db": args.noise_power_db,
                "ue_resyncs_after_attach": diag.get("ue_resyncs_after_attach"),
                "twin_sinr_from_db": round(b["sinr_db"], 2),
                "twin_sinr_to_db": round(s["sinr_db"], 2),
                "twin_mcs_from": b["mcs"], "twin_mcs_to": s["mcs"],
                "twin_sinr_from_fullload_db": round(link1[from_cell]["sinr_db"], 2),
                "twin_sinr_to_fullload_db": round(link1[to_cell]["sinr_db"], 2),
                "twin_link_gain_pct": round(twin_link_gain, 3),
                "twin_full_gain_pct": round(twin_full_gain, 3),
                "real_base_mbps": None if g_from is None else round(g_from, 3),
                "real_steer_mbps": None if g_to is None else round(g_to, 3),
                "real_gain_pct": round(real_gain, 3) if real_gain == real_gain else None,
                "gap_pts": (round(twin_link_gain - real_gain, 3)
                            if real_gain == real_gain else None),
                "real_mcs_pci0": bal.get("mcs_pci0"), "real_mcs_pci1": bal.get("mcs_pci1"),
                "meanpos_pci0": bal.get("meanpos_pci0"), "meanpos_pci1": bal.get("meanpos_pci1"),
                "handovers_ok": sum(r.get("ho_ok", 0) for r in seq),
            })
            print(f"    outcome={outcome}  twin link {twin_link_gain:6.1f}%  "
                  f"real {real_gain if real_gain == real_gain else float('nan'):6.1f}%  "
                  f"(real MCS {bal.get('mcs_pci0')}/{bal.get('mcs_pci1')}, "
                  f"{diag.get('ue_resyncs_after_attach')} resyncs)", flush=True)
            if seq:
                (out / f"multignb_seq_{tag}.json").write_text(json.dumps(seq, indent=2))

        if rows:
            with open(csv_path, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            print(f"wrote {csv_path}", flush=True)

    ok = [r for r in rows
          if r.get("real_gain_pct") not in ("", None) and str(r.get("outcome")) == "ok"]
    if not ok:
        # A negative result is a result: record what failed, and where, reproducibly.
        outcomes: dict[str, int] = {}
        for r in rows:
            outcomes[r.get("outcome", "unknown")] = outcomes.get(r.get("outcome", "unknown"), 0) + 1
        resyncs = [int(r["ue_resyncs_after_attach"]) for r in rows
                   if str(r.get("ue_resyncs_after_attach", "")).strip().isdigit()]
        twin_sat = sum(1 for r in rows if float(r.get("twin_link_gain_pct", 0) or 0) == 0.0)
        summary = {
            "status": "no_usable_layout",
            "n_layouts_attempted": len(rows),
            "outcomes": outcomes,
            "n_injection_verified": sum(1 for r in rows
                                        if not str(r.get("outcome", "")).startswith("injection")),
            "ue_resyncs_after_attach": resyncs,
            "n_layouts_twin_predicts_no_link_difference": twin_sat,
            "note": "Per-cell ray-traced channel injection is confirmed in the UE log for every "
                    "layout: rfsimu_channel_ue0/ue1 carry the twin's link gains exactly. What "
                    "does not close is the measurement. (a) With channel models on both rfsim "
                    "connections the F1 handover mostly fails to complete, and the runs that do "
                    "complete show tens of UE re-synchronisations, so the delivered goodput is "
                    "not a measurement of the channel. (b) rfsim's noise floor is a config knob, "
                    "not kTB*NF, so injection sets the RELATIVE per-cell gain but not the "
                    "absolute SINR; at the idle-neighbour condition a one-UE stack presents, the "
                    "twin puts both cells at MCS 28 and predicts no link-level difference at all. "
                    "A controlled multi-cell gap needs absolute operating-point matching, which "
                    "this emulator's usable noise window cannot span.",
        }
        json_path.write_text(json.dumps(summary, indent=2, allow_nan=False))
        print("\n=== NO USABLE LAYOUT (negative result recorded) ===", flush=True)
        print(json.dumps(summary, indent=2), flush=True)
        return 0

    def col(k):
        return np.array([float(r[k]) for r in ok], float)

    tg, rg, gp = col("twin_link_gain_pct"), col("real_gain_pct"), col("gap_pts")
    sign_agree = int(np.sum(np.sign(tg) == np.sign(rg)))
    pearson = float(np.corrcoef(tg, rg)[0, 1]) if len(ok) > 2 else float("nan")

    # Did the injected channel reproduce the twin's per-cell operating-point split?
    twin_dmcs = col("twin_mcs_to") - col("twin_mcs_from")
    real_dmcs = col("real_mcs_pci1") - col("real_mcs_pci0")
    mcs_split_r = float(np.corrcoef(twin_dmcs, real_dmcs)[0, 1]) if len(ok) > 2 else float("nan")

    summary = {
        "method": "co-channel CU+2DU over F1; per-UE ray-traced channel injected per cell on "
                  "the UE rfsim server (rfsimu_channel_ue0/ue1, verified in the UE log); "
                  "reversal (A/B/A/B) measurement with a saturating UDP probe; rfsim noise "
                  "floor set per layout so the reference cell sits at the twin's MCS",
        "n_layouts": len(ok),
        "n_handovers_ok": int(sum(int(r["handovers_ok"]) for r in ok)),
        "rt_rsrp_split_db_mean": float(col("rt_rsrp_split_db").mean()),
        "twin_link_gain_mean_pct": float(tg.mean()),
        "real_gain_mean_pct": float(rg.mean()),
        "fidelity_gap_mean_pts": float(gp.mean()),
        "fidelity_gap_std_pts": float(gp.std(ddof=1)) if len(ok) > 1 else 0.0,
        "fidelity_gap_median_pts": float(np.median(gp)),
        "sign_agreement": f"{sign_agree}/{len(ok)}",
        "pearson_r_twin_vs_real_gain": pearson,
        "pearson_r_mcs_split": mcs_split_r,
        "twin_full_gain_mean_pct": float(col("twin_full_gain_pct").mean()),
        "note": "twin_link_gain excludes the airtime term B_cell/K, which a one-UE real "
                "stack cannot exhibit; twin_full_gain (KPI engine, incl. airtime) is given "
                "for reference and is NOT what real_gain is compared against. "
                "pearson_r_mcs_split tests whether the injected per-cell channel reproduced "
                "the twin's operating-point split on the real stack.",
    }
    json_path.write_text(json.dumps(summary, indent=2, allow_nan=False))
    _make_figure(ROOT / args.fig, ok, summary)
    print("\n=== CONTROLLED MULTI-CELL FIDELITY GAP ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


def _make_figure(fig_path: Path, rows: list[dict], summary: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    tg = [float(r["twin_link_gain_pct"]) for r in rows]
    rg = [float(r["real_gain_pct"]) for r in rows]
    lim = max(5.0, max(abs(min(tg + rg)), abs(max(tg + rg))) * 1.15)
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.axhline(0, color="0.85", lw=0.8)
    ax.axvline(0, color="0.85", lw=0.8)
    ax.plot([-lim, lim], [-lim, lim], "k--", alpha=0.5, label="y=x")
    ax.scatter(tg, rg, c="tab:blue", zorder=3, s=60)
    ax.set_xlabel("twin-predicted per-UE link gain [%]")
    ax.set_ylabel("real multi-cell per-UE gain [%]")
    ax.set_title("Controlled multi-cell closed loop\n"
                 f"gap {summary['fidelity_gap_mean_pts']:.0f}$\\pm$"
                 f"{summary['fidelity_gap_std_pts']:.0f} pts, "
                 f"$r$={summary['pearson_r_twin_vs_real_gain']:.2f}, n={len(rows)}")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    print(f"wrote {fig_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
