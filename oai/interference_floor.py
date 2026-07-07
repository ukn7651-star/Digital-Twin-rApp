#!/usr/bin/env python3
"""CLI: turn the twin's inter-cell interference into per-UE OAI noise floors.

Loads the exported ray-traced channel (``output/channel/cfr.npy`` + ``network.json``),
computes each UE's interference rise with ``dtrapp.oai_bridge``, and writes:
  * ``interference_floor.conf`` - an OAI channelmod snippet with one per-client
    model (``rfsimu_channel_ue{i}``) per UE, each carrying its noise_power_dB, and
  * ``interference_floor.csv`` - the per-UE thermal/interference/rise/SINR values.

Include the generated ``channelmod`` block in the gNB/UE conf so each emulated
link's noise floor reflects the multi-cell network (see oai/README_full_stack.md).

This script (and the core in dtrapp/oai_bridge.py) is pure Python and unit-tested;
consuming the config in a live multi-UE OAI run is done on a full host.

Usage:
    python3 oai/interference_floor.py [channel_dir] [--config configs/example.yaml]
        [--baseline-noise-db -50] [--out output/channel]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

# Allow running as a plain script (python3 oai/interference_floor.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtrapp.oai_bridge import (
    floors_to_rows,
    per_ue_interference_floor,
    write_per_ue_noise_configs,
)
from dtrapp.runner.rapp_cli import _load_config, load_network


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel_dir", nargs="?", default="output/channel")
    ap.add_argument("--config", default="configs/example.yaml")
    ap.add_argument("--baseline-noise-db", type=float, default=-50.0,
                    help="interference-free OAI noise_power_dB (calibrate on host)")
    ap.add_argument("--out", default=None, help="output dir (default: channel_dir)")
    args = ap.parse_args()

    d = Path(args.channel_dir)
    out_dir = Path(args.out) if args.out else d
    out_dir.mkdir(parents=True, exist_ok=True)

    cfr = np.load(d / "cfr.npy")
    network = load_network(d / "network.json")
    config = _load_config(args.config)

    floors = per_ue_interference_floor(network, cfr, config)
    conf_path = out_dir / "interference_floor.conf"
    write_per_ue_noise_configs(floors, conf_path, args.baseline_noise_db)

    csv_path = out_dir / "interference_floor.csv"
    rows = floors_to_rows(floors)
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    rises = np.array([f.rise_db for f in floors])
    print(f"{len(floors)} UEs: interference rise mean {rises.mean():.2f} dB, "
          f"max {rises.max():.2f} dB (UE {floors[int(rises.argmax())].ue_id})")
    print(f"wrote {conf_path}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
