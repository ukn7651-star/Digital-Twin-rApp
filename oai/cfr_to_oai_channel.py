#!/usr/bin/env python3
"""Bridge: Sionna RT channel (CFR)  ->  channel taps for OAI's rfsimulator.

The `dtrapp` pipeline exports the ray-traced channel to `output/channel/cfr.npy`
(plus `network.json`). This script converts that frequency-domain channel into a
small set of time-domain taps (delay + complex gain) per cell->UE link, which is
the form OAI's channel emulator uses.

Pipeline: CFR (frequency) --IFFT over subcarriers--> CIR (time) --keep strongest
N taps--> per-link taps.

STATUS: this produces the taps and documents the mapping. Feeding them into the
running rfsimulator requires OAI's external-channel / channel-emulator interface
(the "OAI meets Sionna RT" / OWDT branch; see NVlabs/sionna-rk). That plumbing is
the remaining integration step.

Usage:  python3 oai/cfr_to_oai_channel.py <output/channel dir> [--taps 4]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def cfr_to_taps(cfr: np.ndarray, num_taps: int = 4):
    """CFR -> (delays, gains) per (UE, cell).

    cfr shape: [num_ues, num_ue_ant, num_cells, num_bs_ant, num_ofdm_symbols, num_sc].
    Returns delays [num_ues, num_cells, num_taps] (subcarrier-sample index) and
    complex gains of the same shape.
    """
    # Average over UE-antenna, BS-antenna and OFDM symbols -> per-(UE,cell) freq response.
    h_freq = cfr.mean(axis=(1, 3, 4))                 # [num_ues, num_cells, num_sc]
    cir = np.fft.ifft(h_freq, axis=-1)                # time-domain impulse response
    order = np.argsort(np.abs(cir), axis=-1)[..., ::-1][..., :num_taps]
    delays = order
    gains = np.take_along_axis(cir, order, axis=-1)
    return delays, gains


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel_dir", help="dir with cfr.npy and network.json (output/channel)")
    ap.add_argument("--taps", type=int, default=4, help="taps per link (OWDT uses ~4)")
    args = ap.parse_args()

    d = Path(args.channel_dir)
    cfr = np.load(d / "cfr.npy")
    net = json.loads((d / "network.json").read_text())

    delays, gains = cfr_to_taps(cfr, args.taps)
    out = d / "oai_taps.npz"
    np.savez(
        out,
        delays=delays,
        gains=gains,
        cells=np.array([c["cell_id"] for c in net["cells"]]),
        ues=np.array([u["ue_id"] for u in net["ues"]]),
    )
    print(f"CFR {cfr.shape} -> taps {gains.shape} (per UE,cell; {args.taps} taps) -> {out}")
    print("Next: feed these taps into OAI's rfsimulator channel emulator "
          "(OWDT / NVlabs/sionna-rk). That OAI-side plumbing is the remaining step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
