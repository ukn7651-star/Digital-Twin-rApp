#!/usr/bin/env python3
"""Measure the REAL fidelity gap: twin-predicted vs real-stack throughput/gain.

Motivation
----------
The analytical twin maps SINR -> throughput with an OAI ``nr_dlsim`` *link-level*
curve (``oai/sinr_throughput_table.json``). The paper's analytical fidelity gap
shows that swapping this curve for an idealized one mis-estimates the rApp's gain.
This script measures the *real* gap: how the twin's per-UE prediction compares to
the **end-to-end goodput a live OAI 5G Standalone stack actually delivers** (real
gNB + 5G core + PDU session + iperf3 over the UPF), which includes everything the
link-level curve omits (MAC scheduling, HARQ, TDD duty cycle, RRC/PDCP/SDAP and
TCP overhead).

Method (honest scope)
---------------------
OAI's rfsimulator is single-gNB, so we cannot execute a multi-cell N2 handover in
one run (the rApp's load-balancing dimension is evaluated on the multi-cell
analytical twin; see ``experiments/``). What the real stack *can* ground is the
**link-abstraction dimension**: for a given operating MCS/SINR, does the real
stack deliver the throughput the twin's link curve predicts?

We pin the live DL to a fixed operating point by capping the gNB scheduler's
``dl_max_mcs`` over a clean channel, sweeping the cap across the MCS range, and
measuring end-to-end iperf3 DL goodput at each fixed MCS. Each measured MCS
indexes the same OAI link curve the twin uses -> a shared SINR axis. This yields a
measured ``real_goodput(MCS/SINR)`` curve, compared against the twin's link-level
prediction ``B*SE(MCS)*(1-BLER)`` (single-UE, full band).

We then take the rApp's per-UE operating points on the analytical twin (baseline
vs steered effective SINR) and read off, for each UE the rApp moves, the
twin-predicted and the real per-UE gain; their difference is the real fidelity
gap on the steering gain.

Every number is reproducible from committed data: the measured points are written
to ``experiments/results/real_goodput_calib.csv`` and the analysis to
``experiments/results/real_fidelity_gap.{csv,json}`` + ``paper/fig_real_fidelity_gap.png``.

Prereqs (validated by oai/README_full_stack.md flow): 5G core healthy, gNB up
(SA rfsim, serveraddr=server) logging to oai_run/gnb.log, iperf3 -s on the data
network (oai-ext-dn 192.168.70.135). Run with --skip-measure to recompute the
analysis from an existing calibration CSV without touching OAI.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dtrapp.kpi.link_curve import load_link_curve
from dtrapp.rapp import association_changes, run_traffic_steering
from dtrapp.runner.rapp_cli import _load_config, load_network

OAI_BUILD = Path.home() / "openairinterface5g/cmake_targets/ran_build/build"
RUN_DIR = ROOT / "oai_run"
GNB_CONF = RUN_DIR / "gnb_sa.conf"     # core-aligned SA gNB conf (Phase 4)
UE_CONF = RUN_DIR / "ue.conf"          # UICC + pdu_sessions (dnn oai, sst 1)
SERVER_IP = "192.168.70.135"           # oai-ext-dn data network (iperf3 server)
DL_FREQ = "3319680000"                 # band 78, 106 PRB, SSB @ 3319.68 MHz
BW_HZ = 20e6                           # cell bandwidth (configs/example.yaml)
BLER = 0.1


def _sh(cmd: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)


def _kill(proc_name: str) -> None:
    _sh(f"sudo pkill -x {proc_name}")


def _kill_all() -> None:
    _kill("nr-uesoftmodem")
    _kill("nr-softmodem")
    time.sleep(3)


def _wait_for(log: Path, pattern: str, timeout: int) -> str | None:
    pat = re.compile(pattern)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if log.exists():
            m = pat.search(log.read_text(errors="ignore"))
            if m:
                return m.group(1) if m.groups() else m.group(0)
        time.sleep(1)
    return None


def _start_gnb(dl_max_mcs: int, tag: str) -> Path:
    """Launch the SA gNB with the DL scheduler MCS capped to dl_max_mcs."""
    base = GNB_CONF.read_text()
    # Insert dl_max_mcs into the MACRLCs block (pin the DL operating point).
    conf_txt = base.replace(
        "pusch_TargetSNRx10 = 200;",
        f"dl_max_mcs = {dl_max_mcs};\n    pusch_TargetSNRx10 = 200;", 1)
    conf = RUN_DIR / f"gnb_cal_{tag}.conf"
    conf.write_text(conf_txt)
    log = RUN_DIR / f"gnb_cal_{tag}.log"
    if log.exists():
        log.unlink()
    subprocess.Popen(
        f'cd "{OAI_BUILD}" && sudo nohup ./nr-softmodem -O "{conf}" --rfsim '
        f'> "{log}" 2>&1 &', shell=True)
    return log


def _parse_dl_mcs(gnb_text: str) -> int | None:
    """Operating DL MCS = peak MCS on dlsch lines carrying active goodput.

    The gNB caps DL MCS at ``dl_max_mcs`` over a clean channel, so steady-state
    lines sit at the cap; the peak (max) is robust to TCP ramp-up / idle lines
    that briefly show MCS 0-1, which a modal statistic would over-weight.
    """
    mcss: list[int] = []
    for line in gnb_text.splitlines():
        if "dlsch_rounds" not in line:
            continue
        m = re.search(r"MCS \(\d+\) (\d+)", line)
        g = re.search(r"goodput ([\d.]+) Mbps", line)
        if m and g and float(g.group(1)) > 0.5:
            mcss.append(int(m.group(1)))
    return max(mcss) if mcss else None


def measure_point(dl_max_mcs: int, dur: int, tag: str) -> dict:
    """Bring up gNB (DL MCS capped) + UE, measure real DL iperf3 goodput."""
    _kill_all()
    gnb_log = _start_gnb(dl_max_mcs, tag)
    if _wait_for(gnb_log, r"Received NGSetupResponse", 45) is None:
        _kill_all()
        return {"dl_max_mcs": dl_max_mcs, "ip": None, "dl_mcs": None, "dl_goodput_mbps": None}
    ue_log = RUN_DIR / f"ue_cal_{tag}.log"
    if ue_log.exists():
        ue_log.unlink()
    subprocess.Popen(
        f'cd "{OAI_BUILD}" && sudo nohup ./nr-uesoftmodem --rfsim -r 106 '
        f"--numerology 1 --band 78 -C {DL_FREQ} -O \"{UE_CONF}\" "
        f'--uicc0.imsi 001010000000001 > "{ue_log}" 2>&1 &', shell=True)
    ip = _wait_for(ue_log, r"oaitun_ue1 successfully configured, IPv4 ([\d.]+)", 45)
    if ip is None:
        _kill_all()
        return {"dl_max_mcs": dl_max_mcs, "ip": None, "dl_mcs": None, "dl_goodput_mbps": None}
    time.sleep(3)
    gnb_off = len(gnb_log.read_text(errors="ignore"))
    goodput = None
    try:
        r = _sh(f"iperf3 -c {SERVER_IP} -B {ip} -t {dur} -R -J", timeout=dur + 25)
        goodput = json.loads(r.stdout)["end"]["sum_received"]["bits_per_second"] / 1e6
    except Exception:
        goodput = None
    mcs = _parse_dl_mcs(gnb_log.read_text(errors="ignore")[gnb_off:])
    _kill_all()
    return {"dl_max_mcs": dl_max_mcs, "ip": ip, "dl_mcs": mcs,
            "dl_goodput_mbps": None if goodput is None else round(goodput, 3)}


def run_calibration(caps: list[int], dur: int) -> list[dict]:
    rows = []
    for i, m in enumerate(caps):
        pt = measure_point(m, dur, tag=f"{i:02d}")
        print(f"  dl_max_mcs={m:2d} -> ip={pt['ip']} operating_mcs={pt['dl_mcs']} "
              f"goodput={pt['dl_goodput_mbps']} Mbps", flush=True)
        rows.append(pt)
    return rows


def se_of_mcs(curve, mcs: int) -> float:
    for p in curve.points:
        if int(p["mcs"]) == mcs:
            return float(p["se_bps_per_hz"])
    # nearest lower MCS
    lower = [p for p in curve.points if int(p["mcs"]) <= mcs]
    return float(max(lower, key=lambda q: q["mcs"])["se_bps_per_hz"]) if lower else 0.0


def sinr_of_mcs(curve, mcs: int) -> float:
    for p in curve.points:
        if int(p["mcs"]) == mcs:
            return float(p["sinr_db"])
    lower = [p for p in curve.points if int(p["mcs"]) <= mcs]
    return float(max(lower, key=lambda q: q["mcs"])["sinr_db"]) if lower else -5.0


def _extent_from_ground(scene_dir: Path):
    lines = (scene_dir / "meshes" / "ground.ply").read_text().splitlines()
    i = lines.index("end_header") + 1
    v = [list(map(float, lines[i + k].split()))[:2] for k in range(4)]
    xs = [a for a, _ in v]
    ys = [b for _, b in v]
    return (min(xs), min(ys), max(xs), max(ys))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel_dir", nargs="?", default="output/channel")
    ap.add_argument("--config", default="configs/example.yaml")
    ap.add_argument("--out", default="experiments/results")
    ap.add_argument("--fig", default="paper/fig_real_fidelity_gap.png")
    ap.add_argument("--dur", type=int, default=8, help="iperf3 seconds per point")
    ap.add_argument("--caps", default="2,5,8,11,14,17,20,23,26,28",
                    help="gNB dl_max_mcs caps to sweep (operating MCS points)")
    ap.add_argument("--seeds", type=int, default=8,
                    help="rApp layouts (random seeds) on the built Berlin scene; "
                         "0 = use the single exported channel_dir instead")
    ap.add_argument("--skip-measure", action="store_true",
                    help="reuse experiments/results/real_goodput_calib.csv")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    calib_csv = out / "real_goodput_calib.csv"
    curve = load_link_curve()

    # ---- 1. real-stack calibration: measured goodput vs operating MCS/SINR ----
    if args.skip_measure and calib_csv.exists():
        import csv as _csv
        rows = []
        with open(calib_csv) as fh:
            for r in _csv.DictReader(fh):
                out_r = {}
                for k, v in r.items():
                    if k == "ip":
                        out_r[k] = v or None
                    else:
                        out_r[k] = float(v) if v not in ("", "None") else None
                rows.append(out_r)
    else:
        caps = [int(x) for x in args.caps.split(",")]
        print(f"[calibration] sweeping {len(caps)} DL MCS operating points on the live SA stack ...",
              flush=True)
        rows = run_calibration(caps, args.dur)
        import csv as _csv
        with open(calib_csv, "w", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=["dl_max_mcs", "ip", "dl_mcs", "dl_goodput_mbps"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"wrote {calib_csv}", flush=True)

    valid = [r for r in rows if r.get("dl_mcs") is not None and r.get("dl_goodput_mbps")]
    if len(valid) < 3:
        print("ERROR: fewer than 3 valid calibration points; cannot build curve.", flush=True)
        return 1

    # measured (SINR, real goodput); collapse duplicate MCS by mean
    by_mcs: dict[int, list[float]] = {}
    for r in valid:
        by_mcs.setdefault(int(r["dl_mcs"]), []).append(float(r["dl_goodput_mbps"]))
    meas_mcs = sorted(by_mcs)
    meas_sinr = np.array([sinr_of_mcs(curve, m) for m in meas_mcs])
    meas_real = np.array([float(np.mean(by_mcs[m])) for m in meas_mcs])
    meas_twin_link = np.array([BW_HZ * se_of_mcs(curve, m) * (1 - BLER) / 1e6 for m in meas_mcs])
    order = np.argsort(meas_sinr)
    meas_sinr, meas_real, meas_twin_link = meas_sinr[order], meas_real[order], meas_twin_link[order]

    def real_rate(sinr_db: float) -> float:
        return float(np.interp(sinr_db, meas_sinr, meas_real))

    def twin_rate(sinr_db: float) -> float:
        # twin single-UE full-band link rate from the OAI curve SE(SINR)
        se = float(np.interp(sinr_db, [p["sinr_db"] for p in sorted(curve.points, key=lambda q: q["sinr_db"])],
                             [p["se_bps_per_hz"] for p in sorted(curve.points, key=lambda q: q["sinr_db"])]))
        return BW_HZ * se * (1 - BLER) / 1e6

    # absolute link-abstraction inflation: twin link-rate vs measured real goodput
    infl = 100.0 * (meas_twin_link - meas_real) / meas_twin_link
    abs_gap = {
        "n_points": len(meas_mcs),
        "mcs_range": [int(meas_mcs[0]), int(meas_mcs[-1])],
        "sinr_range_db": [float(meas_sinr.min()), float(meas_sinr.max())],
        "mean_twin_link_mbps": float(meas_twin_link.mean()),
        "mean_real_goodput_mbps": float(meas_real.mean()),
        "mean_inflation_pct": float(infl.mean()),
        "median_inflation_pct": float(np.median(infl)),
    }

    # ---- 2. rApp per-UE operating points on the twin, evaluated on both curves ----
    config = _load_config(args.config)
    lo, hi = float(meas_sinr.min()), float(meas_sinr.max())

    def _eval_layout(steer, seed):
        base_by = {u.ue_id: u for u in steer.baseline.ues}
        steer_by = {u.ue_id: u for u in steer.steered.ues}
        moved_ids = {m["ue_id"] for m in association_changes(steer.baseline, steer.steered)}
        rows = []
        for uid in sorted(base_by, key=lambda s: (len(s), s)):
            b, s = base_by[uid], steer_by[uid]
            sb = float(np.clip(b.sinr_db, lo, hi))
            ss = float(np.clip(s.sinr_db, lo, hi))
            tw_b, tw_s = twin_rate(sb), twin_rate(ss)
            re_b, re_s = real_rate(sb), real_rate(ss)
            twin_gain = 100.0 * (tw_s - tw_b) / tw_b if tw_b > 0 else float("nan")
            real_gain = 100.0 * (re_s - re_b) / re_b if re_b > 0 else float("nan")
            rows.append({
                "seed": seed, "ue_id": uid, "moved": int(uid in moved_ids),
                "sinr_base_db": round(b.sinr_db, 2), "sinr_steer_db": round(s.sinr_db, 2),
                "twin_base_mbps": round(tw_b, 3), "twin_steer_mbps": round(tw_s, 3),
                "real_base_mbps": round(re_b, 3), "real_steer_mbps": round(re_s, 3),
                "twin_gain_pct": round(twin_gain, 3), "real_gain_pct": round(real_gain, 3),
                "fidelity_gap_pts": round(twin_gain - real_gain, 3),
            })
        return rows

    per_ue = []
    if args.seeds > 0:
        from dataclasses import replace

        from dtrapp.network import RandomNetworkSource
        from dtrapp.propagation import SionnaPropagationEngine

        scene_dir = ROOT / "output" / "scene"
        ext = _extent_from_ground(scene_dir)
        eng = SionnaPropagationEngine(str(scene_dir / "scene.xml"), config)
        print(f"[twin] evaluating rApp over {args.seeds} layouts (Berlin scene) ...", flush=True)
        for seed in range(args.seeds):
            cfg_s = replace(config, seed=seed)
            net = RandomNetworkSource(cfg_s, ext).generate()
            cfr_s = eng.compute_cfr(net)
            steer = run_traffic_steering(net, cfr_s, cfg_s)
            rows = _eval_layout(steer, seed)
            per_ue += rows
            nmoved = sum(r["moved"] for r in rows)
            print(f"   seed {seed}: {nmoved} UE(s) moved", flush=True)
    else:
        d = Path(args.channel_dir)
        cfr = np.load(d / "cfr.npy")
        network = load_network(d / "network.json")
        per_ue = _eval_layout(run_traffic_steering(network, cfr, config), 0)

    mv = [r for r in per_ue if r["moved"]]
    def _arr(rows_, k):
        return np.array([r[k] for r in rows_ if not (isinstance(r[k], float) and np.isnan(r[k]))], float)
    summary = {
        "abs_link_fidelity": abs_gap,
        "n_layouts": (args.seeds if args.seeds > 0 else 1),
        "n_ue": len(per_ue),
        "n_moved": len(mv),
        "moved_twin_gain_mean_pct": float(_arr(mv, "twin_gain_pct").mean()) if mv else 0.0,
        "moved_real_gain_mean_pct": float(_arr(mv, "real_gain_pct").mean()) if mv else 0.0,
        "moved_fidelity_gap_mean_pts": float(_arr(mv, "fidelity_gap_pts").mean()) if mv else 0.0,
        "moved_fidelity_gap_std_pts": float(_arr(mv, "fidelity_gap_pts").std()) if mv else 0.0,
    }

    import csv as _csv
    with open(out / "real_fidelity_gap.csv", "w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=list(per_ue[0].keys()))
        w.writeheader()
        w.writerows(per_ue)
    (out / "real_fidelity_gap.json").write_text(json.dumps(summary, indent=2))

    _make_figure(Path(args.fig), meas_sinr, meas_real, meas_twin_link, mv, summary)

    print("\n=== REAL FIDELITY GAP ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {out/'real_fidelity_gap.csv'}\nwrote {out/'real_fidelity_gap.json'}", flush=True)
    return 0


def _make_figure(fig_path: Path, sinr, real, twin_link, moved_rows, summary) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].plot(sinr, twin_link, "o-", label="twin (OAI link curve, $B\\cdot SE$)", lw=2)
    ax[0].plot(sinr, real, "s-", label="real OAI SA (iperf3 goodput)", lw=2)
    ax[0].set_xlabel("operating SINR [dB]")
    ax[0].set_ylabel("downlink rate [Mbps]")
    ax[0].set_title(f"Link-abstraction fidelity\n(real is {summary['abs_link_fidelity']['mean_inflation_pct']:.0f}% below link-level)")
    ax[0].grid(True, alpha=0.3)
    ax[0].legend(fontsize=8)
    if moved_rows:
        tg = [r["twin_gain_pct"] for r in moved_rows]
        rg = [r["real_gain_pct"] for r in moved_rows]
        lim = max(1.0, max(abs(min(tg + rg)), abs(max(tg + rg))) * 1.1)
        ax[1].plot([-lim, lim], [-lim, lim], "k--", alpha=0.5, label="y=x (perfect)")
        ax[1].scatter(tg, rg, c="tab:red", zorder=3)
        ax[1].set_xlabel("twin-predicted per-UE gain [%]")
        ax[1].set_ylabel("real-stack per-UE gain [%]")
        ax[1].set_title(f"rApp steering gain: gap={summary['moved_fidelity_gap_mean_pts']:.1f} pts")
        ax[1].grid(True, alpha=0.3)
        ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    print(f"wrote {fig_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
