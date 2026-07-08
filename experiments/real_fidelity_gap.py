#!/usr/bin/env python3
"""Measure the REAL fidelity gap: twin-predicted vs real-stack throughput/gain.

Motivation
----------
The analytical twin maps SINR -> throughput with an OAI ``nr_dlsim`` *link-level*
curve (``oai/sinr_throughput_table.json``). ``experiments/fidelity_gap.py`` shows
that swapping this curve for an idealized one mis-estimates the rApp's gain. This
script measures the *real* gap: how the twin's prediction compares to the
**end-to-end goodput a live OAI 5G Standalone stack actually delivers** (real gNB
+ 5G core + PDU session + iperf3 over the UPF), which includes everything the
link-level curve omits (TDD frame structure, DMRS/PDCCH, HARQ, RLC/PDCP/SDAP/GTP
headers, scheduler dynamics) plus the rfsimulator's own compute ceiling.

Method (honest scope)
---------------------
OAI's rfsimulator gives one gNB per UE-facing carrier, so a single run cannot
execute a multi-cell handover; that is ``experiments/multignb_fidelity_gap.py``.
What one gNB *can* ground is the **link-abstraction dimension**: at a given
operating MCS, does the real stack deliver the rate the twin's link curve predicts?

We pin the DL operating point by capping the gNB scheduler's ``dl_max_mcs`` over a
clean channel, sweep the cap across the MCS range, and measure end-to-end goodput
at each fixed MCS. Each measured MCS indexes the same OAI curve the twin uses, so
both live on one SINR axis.

Three corrections over the first version of this experiment, each of which moved
the headline number:

1. **Bandwidth.** The live gNB runs 106 PRB at 30 kHz SCS = 38.16 MHz occupied,
   not the 20 MHz of ``configs/example.yaml``. Comparing a 20 MHz link rate against
   a 38.16 MHz cell's goodput understated the gap. ``B`` is now read from the gNB
   conf, so twin and stack are compared at the same bandwidth.
2. **Instrument.** The original measurement started an 8 s TCP flow 3 s after attach --
   entirely inside slow start, so it reported where the congestion window happened to be
   rather than what the channel could carry. We now settle, then measure TCP's plateau.
   (A saturating UDP source is the textbook alternative and does not work here: in reverse
   mode iperf3 reports the *sending* rate, so with the gNB pinned to ``dl_max_mcs = 4`` --
   a ~10 Mbps MAC -- an 8 Mbps offer reads exactly 8.00 Mbps and a 20 Mbps offer exactly
   20.00 Mbps, both at ~0% loss. Raising the offer until loss appears starves iperf3's
   control connection, which rides the same PDU session.) TCP self-clocks and cannot
   exceed the channel; its plateau is min(channel capacity, transport/compute ceiling),
   and that ceiling is itself part of the twin-vs-stack gap, which we report rather
   than hide.
3. **The twin's own model.** The per-UE steering gain is now read with the airtime
   share ``B_cell/K`` included -- that share is the rApp's actual mechanism. The
   real counterpart applies the *same* ``B_cell/K`` to the measured spectral
   efficiency, so the airtime term cancels in the ratio and the residual gap
   isolates the link abstraction instead of silently deleting the load-balancing
   benefit (which made every steered UE look like a loss).

We also report the gap *as a function of the operating point*: it is not a constant
protocol overhead. A constant overhead would leave ``goodput/SE`` flat; it is not,
which separates the fixed costs (TDD duty, headers) from the rfsimulator's ceiling.

Every number is reproducible from committed data: measured points in
``experiments/results/real_goodput_calib.csv``, analysis in
``experiments/results/real_fidelity_gap.{csv,json}`` and
``paper/fig_real_fidelity_gap.png``.

Prereqs: 5G core healthy, gNB conf at oai_run/gnb_sa.conf, iperf3 -s on the data
network (oai-ext-dn 192.168.70.135). ``--skip-measure`` recomputes the analysis
from the committed calibration CSV without touching OAI.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dtrapp.kpi.link_curve import LinkCurve, load_link_curve
from dtrapp.rapp import association_changes, run_traffic_steering
from dtrapp.runner.rapp_cli import _load_config, load_network

OAI_BUILD = Path.home() / "openairinterface5g/cmake_targets/ran_build/build"
RUN_DIR = ROOT / "oai_run"
GNB_CONF = RUN_DIR / "gnb_sa.conf"     # core-aligned SA gNB conf (monolithic)
UE_CONF = RUN_DIR / "ue.conf"          # UICC + pdu_sessions (dnn oai, sst 1)
SERVER_IP = "192.168.70.135"           # oai-ext-dn data network (iperf3 server)
DL_FREQ = "3319680000"                 # band 78, 106 PRB, SSB @ 3319.68 MHz
BLER = 0.1

# 38.331 TDD-UL-DL-Pattern dl-UL-TransmissionPeriodicity enum -> milliseconds.
_TDD_PERIOD_MS = {0: 0.5, 1: 0.625, 2: 1.0, 3: 1.25, 4: 2.0, 5: 2.5, 6: 5.0, 7: 10.0}
_SYMS_PER_SLOT = 14


def _sh(cmd: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)


def _kill_all() -> None:
    _sh("sudo pkill -x nr-uesoftmodem; sudo pkill -x nr-softmodem; true")
    time.sleep(4)


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


def _conf_int(text: str, key: str) -> int:
    m = re.search(rf"^\s*{key}\s*=\s*(\d+)", text, re.M)
    if m is None:
        raise ValueError(f"{key} not found in gNB conf")
    return int(m.group(1))


def carrier_geometry(conf_text: str) -> dict:
    """Occupied bandwidth and DL duty cycle of the live cell, read from its conf.

    The twin's link-level rate must be evaluated at the *cell's* bandwidth, and the
    TDD duty cycle is the one component of the twin-vs-real gap that is a known,
    exactly computable constant -- worth separating from everything else.
    """
    n_prb = _conf_int(conf_text, "dl_carrierBandwidth")
    mu = _conf_int(conf_text, "dl_subcarrierSpacing")          # 0:15k 1:30k ...
    scs = 15e3 * (2 ** mu)
    bw = n_prb * 12 * scs

    period_ms = _TDD_PERIOD_MS[_conf_int(conf_text, "dl_UL_TransmissionPeriodicity")]
    slots_per_period = int(round(period_ms * (2 ** mu)))       # slots per ms = 2^mu
    dl_syms = (_conf_int(conf_text, "nrofDownlinkSlots") * _SYMS_PER_SLOT
               + _conf_int(conf_text, "nrofDownlinkSymbols"))
    return {
        "num_prb": n_prb, "scs_hz": scs, "bandwidth_hz": bw,
        "tdd_period_ms": period_ms, "slots_per_period": slots_per_period,
        "dl_duty": dl_syms / (slots_per_period * _SYMS_PER_SLOT),
    }


# --------------------------------------------------------------------------
# 1. Real-stack calibration: delivered goodput at a pinned DL MCS
# --------------------------------------------------------------------------
def _start_gnb(dl_max_mcs: int, tag: str) -> Path:
    base = GNB_CONF.read_text()
    conf_txt = base.replace(
        "pusch_TargetSNRx10 = 200;",
        f"dl_max_mcs = {dl_max_mcs};\n    pusch_TargetSNRx10 = 200;", 1)
    conf = RUN_DIR / f"gnb_cal_{tag}.conf"
    conf.write_text(conf_txt)
    log = RUN_DIR / f"gnb_cal_{tag}.log"
    log.unlink(missing_ok=True)
    subprocess.Popen(
        f'cd "{OAI_BUILD}" && sudo nohup ./nr-softmodem -O "{conf}" --rfsim '
        f'> "{log}" 2>&1 &', shell=True)
    return log


_DLSCH = re.compile(r"MCS \(\d+\) (\d+) CCE fail \d+, goodput ([\d.]+) Mbps")


def _parse_dl_mcs(gnb_text: str) -> int | None:
    """Operating DL MCS: the peak MCS on dlsch lines carrying real traffic.

    Link adaptation converges to ``dl_max_mcs`` once traffic flows; the peak is robust
    to the handful of MCS-0 lines emitted before it starts.
    """
    mcss = [int(m.group(1)) for m in _DLSCH.finditer(gnb_text) if float(m.group(2)) > 0.5]
    return max(mcss) if mcss else None


def _parse_mac_goodput(gnb_text: str) -> float | None:
    """Peak MAC-layer DL throughput the scheduler reports (an EWMA of scheduled bytes).

    Recorded alongside the end-to-end goodput as a sanity check: it bounds what the
    radio delivered, independent of anything above the MAC.
    """
    gps = [float(m.group(2)) for m in _DLSCH.finditer(gnb_text) if float(m.group(2)) > 0.5]
    return max(gps) if gps else None


def measure_point(dl_max_mcs: int, dur: int, settle: int, tag: str) -> dict:
    """Bring up gNB (DL MCS capped) + UE, measure delivered DL UDP goodput."""
    empty = {"dl_max_mcs": dl_max_mcs, "ip": None, "dl_mcs": None,
             "dl_goodput_mbps": None, "mac_goodput_mbps": None}
    _kill_all()
    gnb_log = _start_gnb(dl_max_mcs, tag)
    if _wait_for(gnb_log, r"Received NGSetupResponse", 60) is None:
        _kill_all()
        return empty
    ue_log = RUN_DIR / f"ue_cal_{tag}.log"
    ue_log.unlink(missing_ok=True)
    subprocess.Popen(
        f'cd "{OAI_BUILD}" && sudo nohup ./nr-uesoftmodem --rfsim -r 106 '
        f"--numerology 1 --band 78 -C {DL_FREQ} -O \"{UE_CONF}\" "
        f'--uicc0.imsi 001010000000001 > "{ue_log}" 2>&1 &', shell=True)
    ip = _wait_for(ue_log, r"oaitun_ue1 successfully configured, IPv4 ([\d.]+)", 90)
    if ip is None:
        _kill_all()
        return empty
    # Let DL link adaptation reach the cap AND TCP leave slow start before measuring.
    time.sleep(settle)
    gnb_off = len(gnb_log.read_text(errors="ignore"))
    goodput = None
    try:
        r = _sh(f"iperf3 -c {SERVER_IP} -B {ip} -t {dur} -R -J", timeout=dur + 90)
        goodput = json.loads(r.stdout)["end"]["sum_received"]["bits_per_second"] / 1e6
    except Exception:
        pass
    gnb_txt = gnb_log.read_text(errors="ignore")[gnb_off:]
    mcs = _parse_dl_mcs(gnb_txt)
    mac = _parse_mac_goodput(gnb_txt)
    _kill_all()
    return {"dl_max_mcs": dl_max_mcs, "ip": ip, "dl_mcs": mcs,
            "dl_goodput_mbps": None if goodput is None else round(goodput, 3),
            "mac_goodput_mbps": None if mac is None else round(mac, 3)}


def run_calibration(caps: list[int], dur: int, settle: int) -> list[dict]:
    rows = []
    for i, m in enumerate(caps):
        pt = measure_point(m, dur, settle, tag=f"{i:02d}")
        print(f"  dl_max_mcs={m:2d} -> ip={pt['ip']} operating_mcs={pt['dl_mcs']} "
              f"goodput={pt['dl_goodput_mbps']} Mbps (MAC {pt['mac_goodput_mbps']} Mbps)",
              flush=True)
        rows.append(pt)
    return rows


# --------------------------------------------------------------------------
# 2. Curve helpers
# --------------------------------------------------------------------------
def se_of_mcs(curve: LinkCurve, mcs: int) -> float:
    lower = [p for p in curve.points if int(p["mcs"]) <= mcs]
    return float(max(lower, key=lambda q: q["mcs"])["se_bps_per_hz"]) if lower else 0.0


def sinr_of_mcs(curve: LinkCurve, mcs: int) -> float:
    lower = [p for p in curve.points if int(p["mcs"]) <= mcs]
    return float(max(lower, key=lambda q: q["mcs"])["sinr_db"]) if lower else -5.0


def _extent_from_ground(scene_dir: Path):
    lines = (scene_dir / "meshes" / "ground.ply").read_text().splitlines()
    i = lines.index("end_header") + 1
    v = [list(map(float, lines[i + k].split()))[:2] for k in range(4)]
    xs = [a for a, _ in v]
    ys = [b for _, b in v]
    return (min(xs), min(ys), max(xs), max(ys))


def _airtime(result) -> dict:
    """{ue_id: airtime share 1/K} -- the twin's equal-airtime PF allocation."""
    load = {c.cell_id: max(c.num_attached, 1) for c in result.cells}
    return {u.ue_id: 1.0 / load[u.serving_cell] for u in result.ues}


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel_dir", nargs="?", default="output/channel")
    ap.add_argument("--config", default="configs/example.yaml")
    ap.add_argument("--out", default="experiments/results")
    ap.add_argument("--fig", default="paper/fig_real_fidelity_gap.png")
    ap.add_argument("--dur", type=int, default=20, help="TCP flow seconds per point")
    ap.add_argument("--settle", type=int, default=20,
                    help="seconds before probing (LA convergence + TCP slow start)")
    ap.add_argument("--caps", default="0,2,4,6,9,12,15,18,21,24,26,28",
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
    geom = carrier_geometry(GNB_CONF.read_text())
    bw_hz = geom["bandwidth_hz"]
    print(f"[cell] {geom['num_prb']} PRB @ {geom['scs_hz']/1e3:.0f} kHz "
          f"=> B = {bw_hz/1e6:.2f} MHz, DL duty = {geom['dl_duty']:.3f}", flush=True)

    # ---- 1. calibration ----------------------------------------------------
    fields = ["dl_max_mcs", "ip", "dl_mcs", "dl_goodput_mbps", "mac_goodput_mbps"]
    if args.skip_measure and calib_csv.exists():
        rows = []
        with open(calib_csv) as fh:
            for r in csv.DictReader(fh):
                rows.append({k: (v or None) if k == "ip"
                             else (float(v) if v not in ("", "None", None) else None)
                             for k, v in r.items()})
    else:
        caps = [int(x) for x in args.caps.split(",")]
        print(f"[calibration] {len(caps)} DL MCS operating points on the live SA stack ...",
              flush=True)
        rows = run_calibration(caps, args.dur, args.settle)
        with open(calib_csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {calib_csv}", flush=True)

    valid = [r for r in rows
             if r.get("dl_mcs") is not None and r.get("dl_goodput_mbps") is not None]
    if len(valid) < 3:
        print("ERROR: fewer than 3 valid calibration points; cannot build curve.", flush=True)
        return 1

    by_mcs: dict[int, list[float]] = {}
    mac_by_mcs: dict[int, list[float]] = {}   # noqa: E501
    for r in valid:
        by_mcs.setdefault(int(r["dl_mcs"]), []).append(float(r["dl_goodput_mbps"]))
        if r.get("mac_goodput_mbps") is not None:
            mac_by_mcs.setdefault(int(r["dl_mcs"]), []).append(float(r["mac_goodput_mbps"]))
    meas_mcs = sorted(by_mcs)
    meas_sinr = np.array([sinr_of_mcs(curve, m) for m in meas_mcs])
    meas_real = np.array([float(np.mean(by_mcs[m])) for m in meas_mcs])
    meas_mac = np.array([float(np.mean(mac_by_mcs[m])) if m in mac_by_mcs else np.nan
                         for m in meas_mcs])
    meas_se = np.array([se_of_mcs(curve, m) for m in meas_mcs])
    order = np.argsort(meas_sinr)
    meas_sinr, meas_real, meas_se = meas_sinr[order], meas_real[order], meas_se[order]
    meas_mac = meas_mac[order]
    meas_twin_link = bw_hz * meas_se * (1 - BLER) / 1e6          # twin link-level rate

    lo, hi = float(meas_sinr.min()), float(meas_sinr.max())
    # Index the measured curves by the *operating MCS*, not by SINR. The twin's rate is a
    # staircase in SINR: it picks an MCS, then a rate. Interpolating the measured curves
    # along SINR instead would compare a staircase against a ramp and manufacture a gap
    # between the knots that is pure interpolation, not physics.
    mcs_grid = np.array(meas_mcs, dtype=float)
    mac_se_grid = meas_mac * 1e6 / bw_hz
    real_se_grid = meas_real * 1e6 / bw_hz

    def _mcs_at(sinr_db: float) -> float:
        return float(np.clip(curve.map_sinr(sinr_db)[0], mcs_grid.min(), mcs_grid.max()))

    def se_real(sinr_db: float) -> float:
        """Spectral efficiency the application receives at the twin's operating MCS."""
        return float(np.interp(_mcs_at(sinr_db), mcs_grid, real_se_grid))

    def se_mac(sinr_db: float) -> float:
        """Spectral efficiency OAI's *MAC* schedules at the twin's operating MCS.

        This is the emulator-independent reference: the MAC is real 5G-NR scheduler code
        and pays TDD duty, DMRS, PDCCH and HARQ. Everything below it (the transport /
        compute ceiling of a CPU software radio) is an artefact of the emulator.
        """
        return float(np.interp(_mcs_at(sinr_db), mcs_grid, mac_se_grid))

    def se_twin(sinr_db: float) -> float:
        """Twin's goodput SE: the OAI staircase, exactly as ``dtrapp.kpi.engine`` uses it."""
        return curve.map_sinr(sinr_db)[1] * (1 - BLER)

    # The twin -> MAC ratio is the twin's own abstraction error, free of the emulator.
    derate_mac = meas_mac / meas_twin_link
    infl_mac = 100.0 * (1 - derate_mac)
    infl = 100.0 * (meas_twin_link - meas_real) / meas_twin_link
    # A constant protocol overhead leaves goodput/SE flat; a throughput ceiling does not.
    implied_bw = meas_real * 1e6 / (meas_se * (1 - BLER))
    tdd_only = bw_hz * meas_se * (1 - BLER) * geom["dl_duty"] / 1e6
    infl_after_tdd = 100.0 * (tdd_only - meas_real) / tdd_only

    abs_gap = {
        "n_points": len(meas_mcs),
        "mcs_range": [int(meas_mcs[0]), int(meas_mcs[-1])],
        "sinr_range_db": [lo, hi],
        "bandwidth_mhz": round(bw_hz / 1e6, 3),
        "dl_duty": round(geom["dl_duty"], 4),
        "mean_twin_link_mbps": float(meas_twin_link.mean()),
        "mean_real_goodput_mbps": float(meas_real.mean()),
        "mean_inflation_pct": float(infl.mean()),
        "median_inflation_pct": float(np.median(infl)),
        "inflation_pct_range": [float(infl.min()), float(infl.max())],
        "median_inflation_after_tdd_pct": float(np.median(infl_after_tdd)),
        # Emulator-independent: twin link rate vs what OAI's MAC schedules.
        "twin_to_mac_derate_mean": float(derate_mac.mean()),
        "twin_to_mac_derate_std": float(derate_mac.std(ddof=1)),
        "twin_to_mac_derate_cv_pct": float(100 * derate_mac.std(ddof=1) / derate_mac.mean()),
        "twin_to_mac_inflation_median_pct": float(np.median(infl_mac)),
        "twin_to_mac_inflation_range_pct": [float(infl_mac.min()), float(infl_mac.max())],
        "twin_to_app_derate_cv_pct": float(100 * (meas_real / meas_twin_link).std(ddof=1)
                                           / (meas_real / meas_twin_link).mean()),
        "implied_bandwidth_mhz_lowest_mcs": float(implied_bw[0] / 1e6),
        "implied_bandwidth_mhz_highest_mcs": float(implied_bw[-1] / 1e6),
        # Where the rate goes: link-level -> TDD duty -> what the MAC actually schedules
        # -> what the application receives. Only the first step is a modelling choice.
        "mac_goodput_mbps_at_max_mcs": (None if np.isnan(meas_mac[-1])
                                        else float(meas_mac[-1])),
        "twin_link_mbps_at_max_mcs": float(meas_twin_link[-1]),
        "twin_x_tdd_mbps_at_max_mcs": float(tdd_only[-1]),
        "real_goodput_mbps_at_max_mcs": float(meas_real[-1]),
    }

    # ---- 2. rApp per-UE operating points, twin curve vs measured curve ------
    config = _load_config(args.config)

    def _eval_layout(steer, seed):
        base_by = {u.ue_id: u for u in steer.baseline.ues}
        steer_by = {u.ue_id: u for u in steer.steered.ues}
        share_b, share_s = _airtime(steer.baseline), _airtime(steer.steered)
        moved_ids = {m["ue_id"] for m in association_changes(steer.baseline, steer.steered)}
        rows = []
        for uid in sorted(base_by, key=lambda s: (len(s), s)):
            b, s = base_by[uid], steer_by[uid]
            # The same airtime share multiplies both curves: the load term is the
            # rApp's mechanism, so it belongs in BOTH gains and cancels in the gap.
            tw_b, tw_s = se_twin(b.sinr_db) * share_b[uid], se_twin(s.sinr_db) * share_s[uid]
            re_b, re_s = se_real(b.sinr_db) * share_b[uid], se_real(s.sinr_db) * share_s[uid]
            mc_b, mc_s = se_mac(b.sinr_db) * share_b[uid], se_mac(s.sinr_db) * share_s[uid]
            outage = (se_twin(b.sinr_db) <= 0.0) or (se_twin(s.sinr_db) <= 0.0)

            def g(x, y):
                return 100.0 * (y - x) / x if x > 0 else float("nan")

            twin_gain, real_gain, mac_gain = g(tw_b, tw_s), g(re_b, re_s), g(mc_b, mc_s)
            rows.append({
                "seed": seed, "ue_id": uid, "moved": int(uid in moved_ids),
                "outage": int(outage),
                "sinr_base_db": round(b.sinr_db, 2), "sinr_steer_db": round(s.sinr_db, 2),
                "twin_gain_pct": round(twin_gain, 3),
                "mac_gain_pct": round(mac_gain, 3),
                "real_gain_pct": round(real_gain, 3),
                "gap_vs_mac_pts": round(twin_gain - mac_gain, 3),
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
            rows = _eval_layout(run_traffic_steering(net, cfr_s, cfg_s), seed)
            per_ue += rows
            print(f"   seed {seed}: {sum(r['moved'] for r in rows)} UE(s) moved", flush=True)
    else:
        d = Path(args.channel_dir)
        per_ue = _eval_layout(
            run_traffic_steering(load_network(d / "network.json"),
                                 np.load(d / "cfr.npy"), config), 0)

    # Only UEs the rApp moved, and whose gain is defined (not served from/into outage).
    mv = [r for r in per_ue if r["moved"] and not r["outage"]
          and r["twin_gain_pct"] == r["twin_gain_pct"]
          and r["real_gain_pct"] == r["real_gain_pct"]
          and r["mac_gain_pct"] == r["mac_gain_pct"]]
    n_moved = sum(1 for r in per_ue if r["moved"])

    def _arr(k):
        return np.array([r[k] for r in mv], float)

    summary = {
        "abs_link_fidelity": abs_gap,
        "n_layouts": (args.seeds if args.seeds > 0 else 1),
        "n_ue": len(per_ue),
        "n_moved": n_moved,
        "n_moved_evaluated": len(mv),
        "n_moved_excluded_outage": n_moved - len(mv),
        "note": "gains include the twin's airtime share 1/K in BOTH curves; the gap is "
                "the residual link-abstraction error, sign preserved (positive = twin "
                "over-predicts the steering gain)",
    }
    if mv:
        summary |= {
            "moved_twin_gain_mean_pct": float(_arr("twin_gain_pct").mean()),
            "moved_mac_gain_mean_pct": float(_arr("mac_gain_pct").mean()),
            "moved_real_gain_mean_pct": float(_arr("real_gain_pct").mean()),
            # Against the real MAC: the constant derate cancels in a ratio, so this
            # isolates whether the twin's RELATIVE predictions are right.
            "gap_vs_mac_mean_pts": float(_arr("gap_vs_mac_pts").mean()),
            "gap_vs_mac_std_pts": (float(_arr("gap_vs_mac_pts").std(ddof=1))
                                   if len(mv) > 1 else 0.0),
            "gap_vs_mac_max_abs_pts": float(np.abs(_arr("gap_vs_mac_pts")).max()),
            # Against delivered goodput: contains the emulator's transport ceiling.
            "moved_fidelity_gap_mean_pts": float(_arr("fidelity_gap_pts").mean()),
            "moved_fidelity_gap_std_pts": (float(_arr("fidelity_gap_pts").std(ddof=1))
                                           if len(mv) > 1 else 0.0),
            "moved_fidelity_gap_median_pts": float(np.median(_arr("fidelity_gap_pts"))),
        }

    with open(out / "real_fidelity_gap.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_ue[0].keys()))
        w.writeheader()
        w.writerows(per_ue)
    (out / "real_fidelity_gap.json").write_text(json.dumps(summary, indent=2, allow_nan=False))

    _make_figure(ROOT / args.fig, meas_sinr, meas_real, meas_mac, meas_twin_link,
                 tdd_only, mv, summary)
    print("\n=== REAL FIDELITY GAP ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


def _make_figure(fig_path: Path, sinr, real, mac, twin_link, tdd_only, moved_rows,
                 summary) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].plot(sinr, twin_link, "o-", label="twin (OAI link curve, $B\\cdot SE$)", lw=2)
    ax[0].plot(sinr, tdd_only, "^--", label="twin $\\times$ TDD DL duty", lw=1.5, alpha=0.8)
    if not np.all(np.isnan(mac)):
        ax[0].plot(sinr, mac, "d-.", label="OAI MAC scheduled", lw=1.5, alpha=0.85)
    ax[0].plot(sinr, real, "s-", label="real OAI SA (TCP goodput, plateau)", lw=2)
    ax[0].set_xlabel("operating SINR [dB]")
    ax[0].set_ylabel("downlink rate [Mbps]")
    m = summary["abs_link_fidelity"]
    ax[0].set_title(f"Link-abstraction fidelity\n(real {m['median_inflation_pct']:.0f}% below "
                    f"link-level; {m['median_inflation_after_tdd_pct']:.0f}% after TDD)")
    ax[0].grid(True, alpha=0.3)
    ax[0].legend(fontsize=8)
    if moved_rows:
        # The whole argument in one panel: against what a real MAC schedules, the twin's
        # RELATIVE predictions are right (points on y=x); against delivered goodput they
        # are not, and the residual is the emulator's transport ceiling.
        tg = [r["twin_gain_pct"] for r in moved_rows]
        mg = [r["mac_gain_pct"] for r in moved_rows]
        rg = [r["real_gain_pct"] for r in moved_rows]
        lim = max(1.0, max(abs(min(tg + mg + rg)), abs(max(tg + mg + rg))) * 1.08)
        ax[1].plot([-lim, lim], [-lim, lim], "k--", alpha=0.5, lw=1, label="y=x (perfect)")
        ax[1].scatter(tg, mg, c="tab:green", marker="d", zorder=3, s=34,
                      label=f"vs OAI MAC ({summary['gap_vs_mac_mean_pts']:+.1f}"
                            f"$\\pm${summary['gap_vs_mac_std_pts']:.1f} pts)")
        ax[1].scatter(tg, rg, c="tab:red", marker="o", zorder=3, s=34, alpha=0.85,
                      label=f"vs app goodput ({summary['moved_fidelity_gap_median_pts']:+.0f} pts median)")
        ax[1].set_xlabel("twin-predicted per-UE steering gain [%]")
        ax[1].set_ylabel("delivered per-UE steering gain [%]")
        ax[1].set_title("rApp steering gain: relative prediction")
        ax[1].grid(True, alpha=0.3)
        ax[1].legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    print(f"wrote {fig_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
