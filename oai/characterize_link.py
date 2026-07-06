#!/usr/bin/env python3
"""Measure the SINR -> (MCS, throughput) curve from OpenAirInterface's real PHY.

Runs OAI's ``nr_dlsim`` (the DL PHY simulator: real LDPC encode/decode, rate
matching, HARQ) across an SNR sweep for each MCS, and records the lowest SNR at
which the first-transmission BLER stays within the target. That staircase IS the
5G-NR link-adaptation curve -- the thing that replaces the Sionna SYS throughput
model. The engine (dtrapp/kpi/link_curve.py) maps each UE's SINR through it.

Output: oai/sinr_throughput_table.json

Usage:
    python3 oai/characterize_link.py [--rb 106] [--frames 15] [--bler-target 0.1]
                                     [--mcs-table 1] [--snr-min -8] [--snr-max 28]
Env: OAI_DIR (default $HOME/openairinterface5g)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

# 5G-NR MCS table 1 (38.214 Table 5.1.3.1-1): index -> (Qm, code_rate x1024).
MCS_TABLE_1 = {
    0: (2, 120), 1: (2, 157), 2: (2, 193), 3: (2, 251), 4: (2, 308), 5: (2, 379),
    6: (2, 449), 7: (2, 526), 8: (2, 602), 9: (2, 679), 10: (4, 340), 11: (4, 378),
    12: (4, 434), 13: (4, 490), 14: (4, 553), 15: (4, 616), 16: (4, 658), 17: (6, 438),
    18: (6, 466), 19: (6, 517), 20: (6, 567), 21: (6, 616), 22: (6, 666), 23: (6, 719),
    24: (6, 772), 25: (6, 822), 26: (6, 873), 27: (6, 910), 28: (6, 948),
}

_LINE = re.compile(r"SNR ([-+]?[\d.]+):\s*Channel BLER \(([-+eE\d.na]+)")


def sweep_mcs(dlsim: str, mcs: int, rb: int, frames: int, snr_min: float,
              snr_max: float, bler_target: float) -> float | None:
    """Return the lowest SNR (dB) where first-tx BLER <= target for this MCS."""
    cmd = [dlsim, f"-n{frames}", f"-R{rb}", f"-s{snr_min}", f"-S{snr_max}", f"-e{mcs}"]
    # nr_dlsim must run from the build dir to find its runtime files.
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                         cwd=str(Path(dlsim).parent)).stdout
    pts = []
    for line in out.splitlines():
        m = _LINE.search(line)
        if not m:
            continue
        try:
            pts.append((float(m.group(1)), float(m.group(2))))
        except ValueError:
            continue
    if not pts:
        return None
    for snr, bler in pts:
        if bler <= bler_target:
            return snr  # first (lowest) SNR meeting the first-tx BLER target
    # nr_dlsim stops the sweep once the link is reliable by its own criterion;
    # if it stopped before snr_max, that last point is the MCS operating SNR.
    last_snr = pts[-1][0]
    return last_snr if last_snr < snr_max - 0.5 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rb", type=int, default=106)
    ap.add_argument("--frames", type=int, default=15)
    ap.add_argument("--bler-target", type=float, default=0.1)
    ap.add_argument("--mcs-table", type=int, default=1)
    ap.add_argument("--snr-min", type=float, default=-8.0)
    ap.add_argument("--snr-max", type=float, default=28.0)
    ap.add_argument("--out", default=str(Path(__file__).with_name("sinr_throughput_table.json")))
    args = ap.parse_args()

    oai_dir = os.environ.get("OAI_DIR", os.path.expanduser("~/openairinterface5g"))
    dlsim = str(Path(oai_dir) / "cmake_targets/ran_build/build/nr_dlsim")
    if not Path(dlsim).exists():
        raise SystemExit(f"nr_dlsim not found at {dlsim}. Build it: "
                         f"(cd {oai_dir}/cmake_targets/ran_build/build && ninja nr_dlsim)")

    points = []
    for mcs, (qm, r1024) in MCS_TABLE_1.items():
        se = qm * r1024 / 1024.0
        thr = sweep_mcs(dlsim, mcs, args.rb, args.frames, args.snr_min, args.snr_max,
                        args.bler_target)
        if thr is None:
            print(f"MCS {mcs:2d}: not reached within [{args.snr_min},{args.snr_max}] dB")
            continue
        points.append({"sinr_db": thr, "mcs": mcs, "se_bps_per_hz": round(se, 4)})
        print(f"MCS {mcs:2d}: SE {se:5.3f} b/s/Hz  reached at SNR {thr:+.1f} dB")

    # Keep a monotone staircase: each higher-SE point must need a higher SINR.
    points.sort(key=lambda p: p["se_bps_per_hz"])
    monotone, last = [], -1e9
    for p in points:
        if p["sinr_db"] > last:
            monotone.append(p)
            last = p["sinr_db"]
    monotone.sort(key=lambda p: p["sinr_db"])

    table = {
        "source": f"OAI nr_dlsim (RB={args.rb}, {args.frames} frames/pt)",
        "bler_target": args.bler_target,
        "mcs_table_index": args.mcs_table,
        "points": monotone,
    }
    Path(args.out).write_text(json.dumps(table, indent=2))
    print(f"\nwrote {len(monotone)} points -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
