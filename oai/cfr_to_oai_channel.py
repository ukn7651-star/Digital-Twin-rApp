#!/usr/bin/env python3
"""Bridge: Sionna RT channel (CFR)  ->  channel taps for OAI's rfsimulator.

The `dtrapp` pipeline exports the ray-traced channel to `output/channel/cfr.npy`
(plus `network.json`). This script converts that frequency-domain channel into a
small set of time-domain taps (delay + complex gain) per cell->UE link, which is
the form OAI's channel emulator uses.

Pipeline: CFR (frequency) --IFFT over subcarriers--> CIR (time) --keep strongest
N taps--> per-link taps.

It writes three things into the channel dir:
  * oai_taps.npz        - all links, for inspection / re-use.
  * oai_rt_taps.txt     - the chosen link's exact complex taps, in the text
                          format read by the OAI patch (openair1/.../random_channel.c
                          oai_rt_inject_channel), which overrides desc->ch so the
                          rfsimulator transmits over the ray-traced channel.
  * gnb_rtchan.conf     - a gNB conf with the rfsim channel model enabled.

Run:  OAI_RT_TAPS=output/channel/oai_rt_taps.txt \
      CONF=output/channel/gnb_rtchan.conf bash oai/run_phytest.sh 30
(run_phytest.sh exports OAI_RT_TAPS for you.)

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
    # Only causal, short delays are physical taps; the upper half of the IFFT is the
    # negative-delay (wrap-around) alias, so mask it out before picking the strongest.
    mag = np.abs(cir).copy()
    mag[..., mag.shape[-1] // 2:] = -1.0
    order = np.argsort(mag, axis=-1)[..., ::-1][..., :num_taps]
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
    ds_us = ds_s * 1e6  # OAI expects the TDL delay-spread scaling in microseconds
    def one(name):
        return (f"    {{ model_name = \"{name}\"; type = \"{model_type}\"; "
                f"ploss_dB = {ploss_db:.2f}; noise_power_dB = -10; "
                f"forgetfact = 0; offset = 0; ds_tdl = {ds_us:.6f}; }}")
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


def write_taps_file(out_txt: Path, delays_idx, gains, scs_hz: float, num_sc: int,
                    path_loss_db: float, model_names) -> int:
    """Write the exact complex taps for one link in the OAI-patch text format.

    delays_idx : IFFT-bin index per tap (0..num_sc-1) -> converted to nanoseconds.
    gains      : complex gain per tap.
    A block is written for each model name (DL + UL) so both directions use the
    ray-traced channel.
    """
    ntaps = len(gains)
    lines = []
    for name in model_names:
        lines.append(f"{name} {ntaps} {path_loss_db:.4f}")
        for k in range(ntaps):
            delay_ns = float(delays_idx[k]) / (scs_hz * num_sc) * 1e9
            lines.append(f"{delay_ns:.6f} {gains[k].real:.9e} {gains[k].imag:.9e}")
    out_txt.write_text("\n".join(lines) + "\n")
    return ntaps


def write_ue_conf(out_conf: Path, ds_s: float, model_type: str) -> None:
    """Minimal UE conf that enables the rfsim DL channel model (client side).

    The UE has no UL power control loop on its receive path, so the DL SNR it
    measures does track the injected path loss - the clean calibration observable.
    """
    text = (
        'rfsimulator = { serveraddr = "127.0.0.1"; options = ("chanmod"); };\n'
        + _channelmod_block(0.0, ds_s, model_type) + "\n"
    )
    out_conf.write_text(text)


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
    ap.add_argument("--model-type", default="AWGN",
                    help="OAI base channel model (AWGN is safe; the RT patch replaces "
                         "the impulse response and sets channel_length itself)")
    ap.add_argument("--ue", type=int, default=None,
                    help="UE index whose channel to inject (default: strongest link)")
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
    u = args.ue if args.ue is not None else int(np.argmin(pl[np.arange(len(serving)), serving]))
    s = int(serving[u])
    num_sc = cfr.shape[-1]
    # Calibration: unit-energy taps carry the multipath shape; path_loss_dB carries
    # the link gain. Map RT loss relative to the best link -> attenuation (<=0 dB),
    # so the best UE keeps ~baseline SNR and weaker UEs drop accordingly.
    pl_rel = float(pl[u, s] - pl.min())
    inj_gain_db = args.ploss_db if args.ploss_db is not None else -round(pl_rel, 2)
    print(f"CFR {cfr.shape} -> taps {gains.shape} -> {d/'oai_taps.npz'}")
    print(f"injecting link: ue{u} -> cell{s}  path_loss={pl[u,s]:.1f} dB "
          f"(rel {pl_rel:.1f} dB)  delay_spread={ds[u,s]*1e9:.1f} ns  "
          f"-> path_loss_dB(gain)={inj_gain_db:.2f}")

    # Exact complex taps for OAI's random_channel() injection hook (both directions).
    taps_txt = d / "oai_rt_taps.txt"
    n = write_taps_file(taps_txt, delays[u, s], gains[u, s], scs, num_sc, inj_gain_db,
                        ["rfsimu_channel_enB0", "rfsimu_channel_ue0"])
    print(f"wrote {n} exact taps -> {taps_txt}")

    if args.base_conf:
        out_conf = d / "gnb_rtchan.conf"
        write_gnb_conf(Path(args.base_conf), out_conf, 0.0, float(ds[u, s]), args.model_type)
        ue_conf = d / "ue_rtchan.conf"
        write_ue_conf(ue_conf, float(ds[u, s]), args.model_type)
        print(f"wrote OAI gNB conf (chanmod enabled, type={args.model_type}) -> {out_conf}")
        print(f"wrote OAI UE conf  (DL chanmod) -> {ue_conf}")
        print(f"run it:  OAI_RT_TAPS={taps_txt} CONF={out_conf} UE_CONF={ue_conf} "
              f"bash oai/run_phytest.sh 30")

    print("\nThe OAI patch (oai_rt_inject_channel in random_channel.c) overrides the "
          "rfsimulator channel with these exact complex taps, so OAI transmits over the "
          "ray-traced channel. path_loss_dB is the calibrated link gain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
