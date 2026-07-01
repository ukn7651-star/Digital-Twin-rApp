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
    h_freq = cfr.mean(axis=(1, 3, 4))                 # [num_ues, num_cells, num_sc]
    cir = np.fft.ifft(h_freq, axis=-1)                # time-domain impulse response
    order = np.argsort(np.abs(cir), axis=-1)[..., ::-1][..., :num_taps]
    return order, np.take_along_axis(cir, order, axis=-1)


def link_pathloss_db(cfr: np.ndarray) -> np.ndarray:
    """Average path loss (dB) per (UE, cell) from |H|^2."""
    p = (np.abs(cfr) ** 2).mean(axis=(1, 3, 4, 5))    # [num_ues, num_cells]
    return -10.0 * np.log10(np.maximum(p, 1e-30))


def rms_delay_spread_s(cfr: np.ndarray, scs_hz: float) -> np.ndarray:
    """RMS delay spread (seconds) per (UE, cell) from the CIR power profile."""
    h_freq = cfr.mean(axis=(1, 3, 4))                 # [num_ues, num_cells, num_sc]
    n = h_freq.shape[-1]
    cir_p = np.abs(np.fft.ifft(h_freq, axis=-1)) ** 2
    tau = np.arange(n) / (scs_hz * n)                 # tap delay (s)
    total = cir_p.sum(-1) + 1e-30
    mean_tau = (cir_p * tau).sum(-1) / total
    mean_tau2 = (cir_p * tau ** 2).sum(-1) / total
    return np.sqrt(np.maximum(mean_tau2 - mean_tau ** 2, 0.0))


def _channelmod_block(ploss_db: float, ds_s: float, model_type: str) -> str:
    ds_ns = ds_s * 1e9
    def one(name):
        return (f"    {{ model_name = \"{name}\"; type = \"{model_type}\"; "
                f"ploss_dB = {ploss_db:.2f}; noise_power_dB = -10; "
                f"forgetfact = 0; offset = 0; ds_tdl = {ds_ns:.4f}; }}")
    return (
        "channelmod = {\n"
        "  max_chan = 10;\n"
        "  modellist = \"modellist_rfsimu_1\";\n"
        "  modellist_rfsimu_1 = (\n"
        f"{one('rfsimu_channel_enB0')},\n"     # DL
        f"{one('rfsimu_channel_ue0')}\n"       # UL
        "  );\n"
        "};\n"
    )


def write_gnb_conf(base_conf: Path, out_conf: Path, ploss_db: float, ds_s: float,
                   model_type: str) -> None:
    """Copy a gNB conf, enable the rfsim channel model, and append a channelmod block."""
    text = base_conf.read_text()
    # Enable the channel model inside the rfsimulator block.
    if "options" not in text.split("rfsimulator", 1)[-1][:200]:
        text = text.replace('serveraddr = "server";',
                            'serveraddr = "server";\n    options = ("chanmod");', 1)
    text += "\n" + _channelmod_block(ploss_db, ds_s, model_type) + "\n"
    out_conf.write_text(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel_dir", help="dir with cfr.npy and network.json (output/channel)")
    ap.add_argument("--taps", type=int, default=4, help="taps per link (OWDT uses ~4)")
    ap.add_argument("--base-conf", default=None,
                    help="base gNB conf to derive an rfsim channel conf from")
    ap.add_argument("--ploss-db", type=float, default=None,
                    help="override the DL path loss (dB) written into the conf")
    ap.add_argument("--model-type", default="TDL_C",
                    help="OAI channel model type (AWGN, TDL_C, ...)")
    args = ap.parse_args()

    d = Path(args.channel_dir)
    cfr = np.load(d / "cfr.npy")
    net = json.loads((d / "network.json").read_text())
    scs = 30e3  # subcarrier spacing used by the RT export (config.subcarrier_spacing_hz)

    # Exact complex taps (for the full-fidelity OAI patch path).
    delays, gains = cfr_to_taps(cfr, args.taps)
    np.savez(d / "oai_taps.npz", delays=delays, gains=gains,
             cells=np.array([c["cell_id"] for c in net["cells"]]),
             ues=np.array([u["ue_id"] for u in net["ues"]]))

    # Per-link path loss + delay spread; serving link = strongest (min path loss).
    pl = link_pathloss_db(cfr)                        # [num_ues, num_cells]
    ds = rms_delay_spread_s(cfr, scs)
    serving = np.argmin(pl, axis=1)
    u = int(np.argmin(pl[np.arange(len(serving)), serving]))  # a representative UE
    s = int(serving[u])
    pl_rel = float(pl[u, s] - pl.min())               # relative to the best link
    print(f"CFR {cfr.shape} -> taps {gains.shape} -> {d/'oai_taps.npz'}")
    print(f"representative link: ue{u} -> cell{s}  path_loss={pl[u,s]:.1f} dB "
          f"(rel {pl_rel:.1f} dB)  delay_spread={ds[u,s]*1e9:.1f} ns")

    if args.base_conf:
        ploss = args.ploss_db if args.ploss_db is not None else round(pl_rel, 2)
        out_conf = d / "gnb_rtchan.conf"
        write_gnb_conf(Path(args.base_conf), out_conf, ploss, float(ds[u, s]), args.model_type)
        print(f"wrote OAI gNB conf (chanmod enabled, ploss={ploss} dB, "
              f"type={args.model_type}) -> {out_conf}")
        print(f"run it:  CONF={out_conf} bash oai/run_phytest.sh 30")

    print("\nNote: the channelmod conf couples OAI's link to the RT path loss + delay "
          "spread. Exact complex-tap injection (using oai_taps.npz) needs an OAI source "
          "patch (OWDT / NVlabs/sionna-rk); absolute path loss also needs link-budget "
          "calibration against OAI's tx-power settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
