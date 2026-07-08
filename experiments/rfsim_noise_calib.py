#!/usr/bin/env python3
"""Calibrate the rfsimulator noise floor: noise_power_dB -> operating DL MCS.

Injecting a UE's ray-traced channels reproduces the *relative* link gain between the
two cells, because ``oai_rt_inject_channel`` normalises the taps to unit energy and
carries the gain in ``path_loss_dB``. It cannot reproduce the *absolute* SINR: in
rfsim the noise floor is a config knob (``noise_power_dB``), not kTB*NF.

So before comparing the twin's predicted steering gain against the delivered one, we
must place the real stack at the twin's operating point. This script measures the
map by muting one cell (-40 dB) and sweeping ``noise_power_dB`` on the other, with
both DUs connected so the per-connection noise addition in ``rxAddInput`` is the
same as in the real experiment. The operating MCS the scheduler converges to is then
inverted through the OAI link curve to give an effective SINR per noise setting.

Outputs: experiments/results/rfsim_noise_calib.{csv,json}
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dtrapp.kpi.link_curve import load_link_curve
from experiments.oai_multicell_stack import RUN, Stack, ensure_iperf_server
from oai.cfr_to_oai_multicell import write_multicell_taps, write_ue_conf

MUTED_DB = -40.0          # the second cell contributes noise, not signal


def sinr_of_mcs(curve, mcs: int) -> float:
    lower = [p for p in curve.points if int(p["mcs"]) <= mcs]
    return float(max(lower, key=lambda q: q["mcs"])["sinr_db"]) if lower else float("nan")


def measure(cfr, ue_idx: int, npdb: float, dur: int, tag: str) -> dict:
    taps = RUN / f"taps_{tag}.txt"
    conf = RUN / f"ue_{tag}.conf"
    write_multicell_taps(taps, cfr, ue_idx, [0, 1], gain_override_db=[0.0, MUTED_DB])
    write_ue_conf(conf, num_cells=2, noise_power_db=npdb)
    stack = Stack(tag=tag, ue_conf=conf, taps=taps, cochannel=True)
    try:
        stack.start()
        inj = dict(stack.injected_models())
        if "rfsimu_channel_ue0" not in inj or "rfsimu_channel_ue1" not in inj:
            raise RuntimeError(f"injection not confirmed: {inj}")
        r = stack.measure(dur=dur)
    finally:
        stack.stop()
    return {"noise_power_db": npdb, "pci": r["pci"], "dl_mcs": r["dl_mcs"],
            "goodput_mbps": None if r["goodput_mbps"] is None else round(r["goodput_mbps"], 3),
            "mac_goodput_mbps": r["mac_goodput_mbps"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfr", default="output/channel/cfr.npy")
    ap.add_argument("--ue", type=int, default=None,
                    help="UE index (default: the one with the strongest link to cell 0; "
                         "a UE in outage has an all-zero CFR and injects silence)")
    ap.add_argument("--noise-list", default="-22,-18,-14,-10,-6,-2",
                    help="rfsim noise floors to sweep. The usable window is narrow: a "
                         "0 dB cell saturates at MCS 28 at low noise and collapses at high")
    ap.add_argument("--dur", type=int, default=15)
    ap.add_argument("--out", default="experiments/results")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    curve = load_link_curve()
    cfr = np.load(ROOT / args.cfr)
    # The 2-cell experiment uses a 2-sector twin; any (ue, cell) pair provides the
    # multipath shape. Gains are overridden, so only the tap shape matters here.
    if cfr.shape[2] < 2:
        print("ERROR: need a >=2-cell CFR", flush=True)
        return 1

    # Gains are overridden below, so only the tap *shape* matters -- but the tap must be
    # non-zero, i.e. the UE must actually see cell 0. Pick the strongest such UE.
    ue = args.ue if args.ue is not None else int(
        np.argmax(np.abs(cfr[:, :, 0]).mean(axis=(1, 2, 3, 4))))
    print(f"[noisecal] UE {ue} (strongest link to cell 0), muted cell at {MUTED_DB} dB",
          flush=True)

    ensure_iperf_server()
    rows = []
    for i, npdb in enumerate(float(x) for x in args.noise_list.split(",")):
        try:
            r = measure(cfr, ue, npdb, args.dur, tag=f"noisecal_{i:02d}")
        except Exception as e:
            print(f"  noise_power_dB={npdb}: ERROR {e}", flush=True)
            continue
        r["eff_sinr_db"] = sinr_of_mcs(curve, r["dl_mcs"]) if r["dl_mcs"] is not None else None
        rows.append(r)
        print(f"  noise_power_dB={npdb:6.1f} -> MCS {r['dl_mcs']} "
              f"(curve SINR {r['eff_sinr_db']}) goodput {r['goodput_mbps']} Mbps", flush=True)

    if not rows:
        return 1
    with open(out / "rfsim_noise_calib.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    good = [r for r in rows if r["dl_mcs"] is not None]
    mcs = [r["dl_mcs"] for r in good]
    monotone = all(a >= b for a, b in zip(mcs, mcs[1:]))   # more noise => not more MCS
    summary = {
        "muted_cell_gain_db": MUTED_DB,
        "n_points": len(good),
        "monotone_in_noise": monotone,
        "conclusion": ("invertible: a target MCS can be requested" if monotone else
                       "NOT invertible: the operating MCS is not monotone in the rfsim noise "
                       "floor, so the reference cell cannot be placed at a target operating "
                       "point. Absolute SINR matching is impossible on this emulator, which is "
                       "why experiments/multignb_fidelity_gap.py claims only a relative "
                       "per-cell gain."),
        "note": "operating MCS the DL scheduler converges to at each rfsim noise floor, "
                "with the second cell muted; eff_sinr_db is that MCS read back through "
                "oai/sinr_throughput_table.json",
        "points": [{"noise_power_db": r["noise_power_db"], "dl_mcs": r["dl_mcs"],
                    "eff_sinr_db": r["eff_sinr_db"]} for r in good],
    }
    (out / "rfsim_noise_calib.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    print("\n=== RFSIM NOISE CALIBRATION ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
