#!/usr/bin/env python3
"""Multi-gNB closed-loop fidelity gap: twin-predicted vs real rApp steering gain.

Runs a 2-cell OAI SA stack (CU + DU-pci0 + DU-pci1 over F1), computes the
traffic-steering rApp decision on a matching 2-cell analytical twin per layout,
applies scripted F1 handovers on the real stack, and measures per-UE iperf3
goodput on each cell before/after the rApp's association change.

Outputs: experiments/results/multignb_fidelity_gap.{csv,json},
         paper/fig_multignb_gap.png

Prereqs: 5G core healthy, OAI built with telnetsrv, host READY (oai/check_host.sh).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dtrapp.config import SimulationConfig
from dtrapp.network import RandomNetworkSource
from dtrapp.propagation import SionnaPropagationEngine
from dtrapp.rapp import association_changes, kpi_metrics, run_traffic_steering
from dtrapp.runner.rapp_cli import _load_config

OAI = Path.home() / "openairinterface5g"
BUILD = OAI / "cmake_targets/ran_build/build"
CU_CONF = OAI / "targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb-cu.sa.f1.conf"
DU0_CONF = OAI / "targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb-du.sa.band78.106prb.rfsim.pci0.conf"
DU1_CONF = OAI / "targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb-du.sa.band78.106prb.rfsim.pci1.conf"
RUN = ROOT / "oai_run"
SERVER_IP = "192.168.70.135"
TELNET_PORT = 9090
DL_FREQ = "3450720000"
IMSI = "001010000000001"
# Twin cell IDs for num_sites=1, sectors_per_site=2
CELL_PCI = {"s0-c0": 0, "s0-c1": 1}


def _sh(cmd: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)


def _kill(*names: str) -> None:
    for n in names:
        _sh(f"sudo pkill -x {n}")
    time.sleep(2)


def _wait_log(log: Path, pattern: str, timeout: int, offset: int = 0) -> re.Match | None:
    pat = re.compile(pattern)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if log.exists():
            txt = log.read_text(errors="ignore")[offset:]
            m = pat.search(txt)
            if m:
                return m
        time.sleep(0.5)
    return None


def _ensure_iperf_server() -> None:
    _sh("sudo docker exec oai-ext-dn pkill iperf3 2>/dev/null; true")
    _sh("sudo docker exec oai-ext-dn iperf3 -s -D")


def _measure_goodput(ip: str, dur: int) -> float | None:
    try:
        r = _sh(f"iperf3 -c {SERVER_IP} -B {ip} -t {dur} -R -J", timeout=dur + 30)
        return json.loads(r.stdout)["end"]["sum_received"]["bits_per_second"] / 1e6
    except Exception:
        return None


def _write_ue_conf(out: Path) -> None:
    """UE conf matching verified handover setup (rfsim server, no chanmod)."""
    text = '''uicc0 = {
  imsi = "001010000000001";
  key = "fec86ba6eb707ed08905757b1bb44b8f";
  opc = "C42449363BBAD02B66D16BC975D77CC1";
  pdu_sessions = ({ dnn = "oai"; nssai_sst = 1; });
}
rfsimulator = ( { serveraddr = "server"; serverport = 4043; } );
'''
    out.write_text(text)



def _kill_all() -> None:
    _sh("sudo pkill -x nr-softmodem; sudo pkill -x nr-uesoftmodem; true")
    time.sleep(3)


def _start_stack(ue_conf: Path, tag: str) -> tuple[Path, Path, Path, Path, str]:
    cu_log = RUN / f"cu_{tag}.log"
    du0_log = RUN / f"du0_{tag}.log"
    du1_log = RUN / f"du1_{tag}.log"
    ue_log = RUN / f"ue_{tag}.log"
    for p in (cu_log, du0_log, du1_log, ue_log):
        if p.exists():
            p.unlink()

    _kill_all()
    subprocess.Popen(
        f'cd "{BUILD}" && sudo nohup ./nr-softmodem -O "{CU_CONF}" '
        f'--telnetsrv --telnetsrv.shrmod ci > "{cu_log}" 2>&1 &', shell=True)
    if _wait_log(cu_log, r"Received NGSetupResponse", 60) is None:
        raise RuntimeError("CU failed NGSetup")

    subprocess.Popen(
        f'cd "{BUILD}" && sudo nohup ./nr-softmodem --rfsim -O "{DU0_CONF}" '
        f'--rfsimulator.[0].serveraddr 127.0.0.1 '
        f'> "{du0_log}" 2>&1 &', shell=True)
    time.sleep(3)

    subprocess.Popen(
        f'cd "{BUILD}" && sudo nohup ./nr-uesoftmodem -C {DL_FREQ} -r 106 '
        f'--numerology 1 --ssb 516 --rfsim -O "{ue_conf}" '
        f'--rfsimulator.[0].serveraddr server --uicc0.imsi {IMSI} '
        f'> "{ue_log}" 2>&1 &', shell=True)
    ip_m = _wait_log(ue_log, r"oaitun_ue1 successfully configured, IPv4 ([\d.]+)", 90)
    if ip_m is None:
        raise RuntimeError("UE attach failed")
    ip = ip_m.group(1)

    subprocess.Popen(
        f'cd "{BUILD}" && sudo nohup ./nr-softmodem --rfsim -O "{DU1_CONF}" '
        f'--rfsimulator.[0].serveraddr 127.0.0.1 '
        f'> "{du1_log}" 2>&1 &', shell=True)
    time.sleep(5)
    return cu_log, du0_log, du1_log, ue_log, ip


def _trigger_ho(cu_log: Path) -> bool:
    off = len(cu_log.read_text(errors="ignore")) if cu_log.exists() else 0
    _sh(f'echo "ci trigger_f1_ho" | nc -N 127.0.0.1 {TELNET_PORT}')
    return _wait_log(cu_log, r"handover for UE .* complete", 30, offset=off) is not None


def _extent(scene_dir: Path):
    lines = (scene_dir / "meshes" / "ground.ply").read_text().splitlines()
    i = lines.index("end_header") + 1
    v = [list(map(float, lines[i + k].split()))[:2] for k in range(4)]
    xs = [a for a, _ in v]
    ys = [b for _, b in v]
    return (min(xs), min(ys), max(xs), max(ys))


def _pct(new: float, old: float) -> float:
    return 100.0 * (new - old) / old if old > 0 else float("nan")



def measure_moved_ue(cfr, network, config, ue_id: str, from_cell: str, to_cell: str,
                     dur: int, tag: str) -> dict:
    ue_conf = RUN / f"ue_mc_{tag}.conf"
    _write_ue_conf(ue_conf)
    cu_log, _, _, ue_log, ip = _start_stack(ue_conf, tag)
    time.sleep(3)
    g0 = _measure_goodput(ip, dur)
    ho_ok = _trigger_ho(cu_log)
    time.sleep(3)
    g1 = _measure_goodput(ip, dur) if ho_ok else None
    pci1 = "PCI: 1" in ue_log.read_text(errors="ignore")
    from_pci = CELL_PCI[from_cell]
    to_pci = CELL_PCI[to_cell]
    by_pci = {0: g0, 1: g1}
    real_base = by_pci.get(from_pci)
    real_steer = by_pci.get(to_pci)
    _kill_all()
    return {
        "ue_id": ue_id, "from_cell": from_cell, "to_cell": to_cell,
        "real_base_mbps": None if real_base is None else round(real_base, 3),
        "real_steer_mbps": None if real_steer is None else round(real_steer, 3),
        "ho_ok": int(ho_ok and pci1),
        "g_pci0_mbps": None if g0 is None else round(g0, 3),
        "g_pci1_mbps": None if g1 is None else round(g1, 3),
    }


def twin_layout(seed: int, config: SimulationConfig, eng: SionnaPropagationEngine, ext):
    cfg = replace(config, seed=seed, num_sites=1, sectors_per_site=2,
                  num_ues=20, neighbor_load=1.0)
    net = RandomNetworkSource(cfg, ext).generate()
    cfr = eng.compute_cfr(net)
    steer = run_traffic_steering(net, cfr, cfg, step_db=0.5, cio_cap_db=12.0)
    moves = association_changes(steer.baseline, steer.steered)
    base_m = kpi_metrics(steer.baseline)
    steer_m = kpi_metrics(steer.steered)
    return net, cfr, cfg, steer, moves, base_m, steer_m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/example.yaml")
    ap.add_argument("--seeds", type=int, default=8,
                    help="number of consecutive seeds 0..N-1 (ignored if --seed-list set)")
    ap.add_argument("--seed-list", default="",
                    help="comma-separated layout seeds (use seeds where twin moves UEs)")
    ap.add_argument("--dur", type=int, default=6, help="iperf3 seconds per measurement")
    ap.add_argument("--out", default="experiments/results")
    ap.add_argument("--fig", default="paper/fig_multignb_gap.png")
    ap.add_argument("--skip-measure", action="store_true")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "multignb_fidelity_gap.csv"
    json_path = out / "multignb_fidelity_gap.json"

    seed_list = [int(x) for x in args.seed_list.split(",") if x.strip()] \
        if args.seed_list.strip() else list(range(args.seeds))
    config = _load_config(args.config)
    scene = ROOT / "output" / "scene"
    ext = _extent(scene)
    eng = SionnaPropagationEngine(str(scene / "scene.xml"), config)

    rows: list[dict] = []
    if args.skip_measure and csv_path.exists():
        with open(csv_path) as fh:
            rows = list(csv.DictReader(fh))
    else:
        _ensure_iperf_server()
        print(f"[multignb] {len(seed_list)} layouts, 2-cell twin + CU/2-DU real stack", flush=True)
        for seed in seed_list:
            print(f"  seed {seed}: ray-trace + twin steering ...", flush=True)
            net, cfr, cfg, steer, moves, base_m, steer_m = twin_layout(seed, config, eng, ext)
            base_by = {u.ue_id: u for u in steer.baseline.ues}
            steer_by = {u.ue_id: u for u in steer.steered.ues}
            twin_gains = {
                "mean": _pct(steer_m["mean_mbps"], base_m["mean_mbps"]),
                "median": _pct(steer_m["median_mbps"], base_m["median_mbps"]),
                "edge": _pct(steer_m["edge_mbps"], base_m["edge_mbps"]),
                "served_edge": _pct(steer_m["served_edge_mbps"], base_m["served_edge_mbps"]),
            }
            if not moves:
                rows.append({
                    "seed": seed, "ue_id": "", "moved": 0, "ho_ok": 0,
                    "from_cell": "", "to_cell": "",
                    "twin_base_mbps": "", "twin_steer_mbps": "",
                    "real_base_mbps": "", "real_steer_mbps": "",
                    "twin_gain_pct": "", "real_gain_pct": "", "gap_pts": "",
                    **{f"twin_{k}_gain_pct": round(v, 3) for k, v in twin_gains.items()},
                    **{f"real_{k}_gain_pct": "" for k in twin_gains},
                })
                print(f"    no UE moved (twin only)", flush=True)
                continue

            mv = moves[0]
            uid = mv["ue_id"]
            b, s = base_by[uid], steer_by[uid]
            tag = f"s{seed}_{uid.replace('-', '')}"
            print(f"    moved {uid}: {mv['from_cell']}->{mv['to_cell']} (real measure) ...", flush=True)
            try:
                meas = measure_moved_ue(cfr, net, cfg, uid, mv["from_cell"], mv["to_cell"],
                                        args.dur, tag)
            except Exception as e:
                print(f"    ERROR: {e}", flush=True)
                meas = {"real_base_mbps": None, "real_steer_mbps": None, "ho_ok": 0,
                        "g_pci0_mbps": None, "g_pci1_mbps": None}
            tw_g = _pct(s.throughput_mbps, b.throughput_mbps)
            re_g = _pct(meas["real_steer_mbps"] or 0, meas["real_base_mbps"] or 0) \
                if meas.get("real_base_mbps") and meas.get("real_steer_mbps") else float("nan")
            rows.append({
                "seed": seed, "ue_id": uid, "moved": 1, **meas,
                "from_cell": mv["from_cell"], "to_cell": mv["to_cell"],
                "twin_base_mbps": round(b.throughput_mbps, 3),
                "twin_steer_mbps": round(s.throughput_mbps, 3),
                "twin_gain_pct": round(tw_g, 3),
                "real_gain_pct": round(re_g, 3) if re_g == re_g else "",
                "gap_pts": round(tw_g - re_g, 3) if re_g == re_g else "",
                **{f"twin_{k}_gain_pct": round(twin_gains[k], 3) for k in twin_gains},
                **{f"real_{k}_gain_pct": round(re_g, 3) if re_g == re_g else "" for k in twin_gains},
            })
            print(f"    twin gain {tw_g:.1f}% real {re_g:.1f}% ho_ok={meas.get('ho_ok')}", flush=True)

        if rows:
            fields: list[str] = []
            for r in rows:
                for k in r:
                    if k not in fields:
                        fields.append(k)
            with open(csv_path, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            print(f"wrote {csv_path}", flush=True)

    moved = [r for r in rows if str(r.get("moved")) == "1" and r.get("real_gain_pct") not in ("", None)]
    ho_ok = sum(1 for r in rows if str(r.get("ho_ok")) == "1")

    def _fvals(key):
        return np.array([float(r[key]) for r in moved if r.get(key) not in ("", None)], float)

    tg, rg, gp = _fvals("twin_gain_pct"), _fvals("real_gain_pct"), _fvals("gap_pts")
    summary = {
        "n_layouts": len(seed_list),
        "n_moved_measured": len(moved),
        "n_handover_ok": ho_ok,
        "method": "CU+2DU F1; scripted telnet ci trigger_f1_ho; 2-cell twin (1 site x 2 sectors)",
        "per_ue_twin_gain_mean_pct": float(tg.mean()) if tg.size else None,
        "per_ue_real_gain_mean_pct": float(rg.mean()) if rg.size else None,
        "per_ue_fidelity_gap_mean_pts": float(gp.mean()) if gp.size else None,
        "per_ue_fidelity_gap_std_pts": float(gp.std()) if gp.size else None,
    }
    for metric in ("mean", "median", "served_edge"):
        tk = f"twin_{metric}_gain_pct"
        rk = f"real_{metric}_gain_pct"
        tv = np.array([float(r[tk]) for r in rows if r.get(tk) not in ("", None)], float)
        rv = np.array([float(r[rk]) for r in moved if r.get(rk) not in ("", None)], float)
        if tv.size:
            summary[f"twin_{metric}_gain_mean_pct"] = float(tv.mean())
        if rv.size:
            summary[f"real_{metric}_gain_mean_pct"] = float(rv.mean())
        if tv.size and rv.size:
            summary[f"{metric}_fidelity_gap_mean_pts"] = float(tv.mean() - rv.mean())

    json_path.write_text(json.dumps(summary, indent=2))
    _make_figure(ROOT / args.fig, moved, summary)
    print("\n=== MULTI-gNB FIDELITY GAP ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


def _make_figure(fig_path: Path, moved_rows: list[dict], summary: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    if not moved_rows:
        return
    tg = [float(r["twin_gain_pct"]) for r in moved_rows]
    rg = [float(r["real_gain_pct"]) for r in moved_rows]
    lim = max(5.0, max(abs(min(tg + rg)), abs(max(tg + rg))) * 1.15)
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot([-lim, lim], [-lim, lim], "k--", alpha=0.5, label="y=x")
    ax.scatter(tg, rg, c="tab:blue", zorder=3, s=60)
    ax.set_xlabel("twin-predicted per-UE gain [%]")
    ax.set_ylabel("real multi-cell per-UE gain [%]")
    gap = summary.get("per_ue_fidelity_gap_mean_pts")
    ax.set_title(f"Multi-cell closed loop\n(gap={gap:.1f} pts, n={len(moved_rows)})" if gap else "Multi-cell closed loop")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    print(f"wrote {fig_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
