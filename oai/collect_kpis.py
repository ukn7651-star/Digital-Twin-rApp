#!/usr/bin/env python3
"""Parse an OAI gNB log into a tidy CSV of per-UE PHY/MAC KPIs.

The gNB prints periodic per-UE lines like:

  UE 1234: dlsch_rounds 60165/.../..., dlsch_errors 1192, ... BLER 0.10000 MCS (0) 9 ... goodput 0.00 Mbps
  UE 1234: ulsch_rounds 60166/.../..., ulsch_errors 1192, ... BLER 0.10000 MCS (0) 9 (Qm 2 ...) NPRB 50 SNR 22.2 (+2.2) dB ... goodput 0.00 Mbps

This extracts direction, HARQ rounds/errors, BLER, MCS, SNR, NPRB and goodput
into a CSV (one row per printed stats line) and prints a short summary.

Usage:  python3 collect_kpis.py <gnb.log> [out.csv]
"""

from __future__ import annotations

import csv
import re
import sys


def _find(pattern: str, line: str, cast=float):
    m = re.search(pattern, line)
    return cast(m.group(1)) if m else None


def parse(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, errors="ignore") as fh:
        for line in fh:
            if "dlsch_rounds" in line:
                direction = "DL"
                rounds = _find(r"dlsch_rounds (\d+)", line, int)
                errors = _find(r"dlsch_errors (\d+)", line, int)
            elif "ulsch_rounds" in line:
                direction = "UL"
                rounds = _find(r"ulsch_rounds (\d+)", line, int)
                errors = _find(r"ulsch_errors (\d+)", line, int)
            else:
                continue
            rows.append(
                {
                    "dir": direction,
                    "rounds": rounds,
                    "errors": errors,
                    "bler": _find(r"BLER ([\d.]+)", line),
                    "mcs": _find(r"MCS \(\d+\) (\d+)", line, int),
                    "snr_db": _find(r"SNR ([-+]?[\d.]+)", line),
                    "nprb": _find(r"NPRB (\d+)", line, int),
                    "goodput_mbps": _find(r"goodput ([\d.]+) Mbps", line),
                }
            )
    return rows


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else float("nan")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: collect_kpis.py <gnb.log> [out.csv]")
        return 1
    rows = parse(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "kpis.csv"
    fields = ["dir", "rounds", "errors", "bler", "mcs", "snr_db", "nprb", "goodput_mbps"]
    with open(out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {out}")
    for d in ("DL", "UL"):
        sub = [r for r in rows if r["dir"] == d]
        if sub:
            print(
                f"  {d}: samples={len(sub)} "
                f"mean SNR={_mean(r['snr_db'] for r in sub):.1f} dB  "
                f"mean MCS={_mean(r['mcs'] for r in sub):.1f}  "
                f"mean goodput={_mean(r['goodput_mbps'] for r in sub):.2f} Mbps"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
