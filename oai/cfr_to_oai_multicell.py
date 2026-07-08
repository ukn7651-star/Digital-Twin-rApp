#!/usr/bin/env python3
"""Bridge: per-cell Sionna RT channels -> a live *multi-cell* OAI rfsimulator stack.

``oai/cfr_to_oai_channel.py`` injects ONE ray-traced link (the strongest) into a
single gNB<->UE rfsim connection. That is enough to ground the *link* dimension,
but not the *association* dimension: with a clean channel on every cell, which
cell is "better" on the real stack has nothing to do with the ray-traced SINR the
twin steers on. This module closes that hole.

Topology (the one ``experiments/multignb_fidelity_gap.py`` runs)
---------------------------------------------------------------
The UE is the rfsimulator **server**; each DU is a **client** that connects to it.
In ``radio/rfsimulator/simulator.cpp::allocCirBuf`` the server names the channel
model of the *n*-th accepted connection ``rfsimu_channel_ue{n-1}``, and
``rxAddInput()`` convolves that connection's samples with that model and
**accumulates** them into the UE's receive buffer::

    out_ptr->r += rx_tmp.r * pathLossLinear + noise * gauss()

So the per-cell downlink channel lives on the **UE**, one model per DU, and the
non-serving DU's waveform is summed in as genuine co-channel interference. Hence:

    rfsimu_channel_ue0  <-  first DU to connect   (DU-pci0 = twin cell c0)
    rfsimu_channel_ue1  <-  second DU to connect  (DU-pci1 = twin cell c1)

We write one taps block per model, taking the taps of link (UE u -> cell c_k) and
the **relative** link gain of that link. The OAI patch (``oai_rt_inject_channel``
in ``random_channel.c``) normalises the taps to unit energy -- they carry only the
multipath *shape* -- and applies ``path_loss_dB`` as the link gain. So the UE
receives DU-k's signal attenuated by exactly the twin's ray-traced gain of link
u->c_k, relative to that UE's strongest cell (which is anchored at 0 dB).

What this reproduces, and what it does not
------------------------------------------
* Reproduced: the **relative** per-cell link gain -- the RSRP split that drives
  association, which is precisely what the rApp steers on.
* Not reproduced: the absolute SINR. rfsim's noise floor is set by
  ``noise_power_dB`` in the channelmod block, not by kTB*NF. Calibrate it once
  against the operating MCS (see ``experiments/rfsim_noise_calib.py``) to place the
  reference cell at the twin's operating point.
* Not reproduced: the multipath delay profile. ``DEFAULT_TAPS = 1`` deliberately.
  The twin exports its CFR over ``num_subcarriers = 128`` at 30 kHz -- a 3.84 MHz
  window whose IFFT resolves delays only to 260 ns. The "taps" it yields therefore sit
  at 0/260/521/781 ns and manufacture a ~780 ns delay spread the ray-traced scene does
  not have, while ~96% of their energy is in the first tap anyway. A single tap carries
  the link gain exactly, which is the quantity the multi-cell experiment needs.
  Resolving real multipath would require exporting the CFR across the cell's full
  38.16 MHz (1272 subcarriers), which would also fix the EESM's sub-band sampling.

Usage
-----
    python3 oai/cfr_to_oai_multicell.py output/channel --ue 10 --cells 0,1 \\
        --out oai_run --noise-power-db -20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

# Reuse the single-link tap extraction so both bridges agree by construction.
try:  # when imported as ``oai.cfr_to_oai_multicell``
    from oai.cfr_to_oai_channel import cfr_to_taps, link_pathloss_db, rms_delay_spread_s
except ImportError:  # when run as a plain script from the repo root
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cfr_to_oai_channel import cfr_to_taps, link_pathloss_db, rms_delay_spread_s

# The rfsimulator server (our UE) names the n-th accepted connection's model
# rfsimu_channel_ue{n-1}. DUs are started in cell order, so connection k <-> cell k.
MODEL_FMT = "rfsimu_channel_ue{k}"
# One tap: the 3.84 MHz CFR export cannot resolve multipath (see the module docstring).
DEFAULT_TAPS = 1


def per_cell_link_gains_db(cfr: np.ndarray, ue: int, cells: list[int]) -> np.ndarray:
    """Ray-traced link gain (dB, <=0) of ``ue`` to each cell, referenced to its best.

    The strongest of this UE's links is anchored at 0 dB so it keeps the rfsim
    baseline SNR; every other cell is attenuated by exactly the twin's RSRP
    difference. Anchoring on the *UE's own best link* (not a global best) keeps
    the absolute operating point constant across layouts, so only the split moves.
    """
    pl = link_pathloss_db(cfr)[ue]                    # [num_cells], loss in dB (>0)
    sel = pl[cells]
    return -(sel - sel.min())                         # 0 dB for the best cell


def build_taps_blocks(cfr: np.ndarray, ue: int, cells: list[int], num_taps: int = DEFAULT_TAPS,
                      gain_override_db: list[float] | None = None):
    """One (model_name, delays_idx, gains, gain_db) block per cell, in DU order.

    ``gain_override_db`` replaces the ray-traced link gains (used by the noise-floor
    calibration, where one cell is muted to isolate the other's operating point).
    """
    delays, gains = cfr_to_taps(cfr, num_taps)        # [nU, nC, T]
    gain_db = (np.asarray(gain_override_db, dtype=float) if gain_override_db is not None
               else per_cell_link_gains_db(cfr, ue, cells))
    return [
        (MODEL_FMT.format(k=k), delays[ue, c], gains[ue, c], float(gain_db[k]))
        for k, c in enumerate(cells)
    ]


def write_multicell_taps(
    out_txt: Path, cfr: np.ndarray, ue: int, cells: list[int],
    scs_hz: float = 30e3, num_taps: int = DEFAULT_TAPS,
    gain_override_db: list[float] | None = None,
) -> dict:
    """Write the taps file consumed by ``OAI_RT_TAPS`` on the UE (rfsim server).

    Format (read by ``oai_rt_inject_channel``)::

        <model_name> <ntaps> <path_loss_dB>
        <delay_ns> <re> <im>       x ntaps

    Returns a diagnostics dict (per-cell gain, delay spread, RSRP split) so the
    caller can assert the injection matches the twin before trusting a run.
    """
    num_sc = cfr.shape[-1]
    ds = rms_delay_spread_s(cfr, scs_hz)
    lines: list[str] = []
    diag: dict = {"ue": int(ue), "cells": list(cells), "models": []}
    for name, d_idx, g, gain_db in build_taps_blocks(cfr, ue, cells, num_taps, gain_override_db):
        # A UE the ray tracer found no path to has an all-zero CFR. The OAI patch
        # normalises taps by their energy, so zero taps inject *silence* -- the UE then
        # simply fails to sync, minutes later, with no hint why. Fail here instead.
        if not np.any(np.abs(g) > 0.0):
            raise ValueError(
                f"UE {ue} has an all-zero ray-traced channel to cell {cells[len(diag['models'])]}"
                f" ({name}); it is in outage and cannot be used for channel injection")
        lines.append(f"{name} {len(g)} {gain_db:.4f}")
        for k in range(len(g)):
            delay_ns = float(d_idx[k]) / (scs_hz * num_sc) * 1e9
            lines.append(f"{delay_ns:.6f} {g[k].real:.9e} {g[k].imag:.9e}")
        diag["models"].append({"model": name, "gain_db": round(gain_db, 4)})
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines) + "\n")

    gains = [m["gain_db"] for m in diag["models"]]
    diag["rsrp_split_db"] = round(float(max(gains) - min(gains)), 4)
    diag["best_cell_idx"] = int(np.argmax(gains))
    diag["delay_spread_ns"] = [round(float(ds[ue, c] * 1e9), 3) for c in cells]
    diag["num_taps"] = int(num_taps)
    return diag


def channelmod_block(num_cells: int, noise_power_db: float, model_type: str = "AWGN") -> str:
    """channelmod block defining one model per DU connection on the UE server.

    ``ploss_dB`` is a placeholder: ``oai_rt_inject_channel`` overwrites
    ``desc->path_loss_dB`` with the per-cell ray-traced gain from the taps file.
    ``noise_power_dB`` is NOT overwritten -- it sets the rfsim noise floor and is
    identical for both cells, so the only difference between them is the RT channel.
    """
    entries = ",\n".join(
        f'    {{ model_name = "{MODEL_FMT.format(k=k)}"; type = "{model_type}"; '
        f"ploss_dB = 0.0; noise_power_dB = {noise_power_db:.2f}; "
        "forgetfact = 0; offset = 0; }"
        for k in range(num_cells)
    )
    return (
        "channelmod = {\n"
        f"  max_chan = {max(num_cells + 1, 10)};\n"
        '  modellist = "modellist_rfsimu_1";\n'
        "  modellist_rfsimu_1 = (\n"
        f"{entries}\n"
        "  );\n"
        "};\n"
    )


def write_ue_conf(
    out_conf: Path,
    num_cells: int,
    noise_power_db: float,
    imsi: str = "001010000000001",
    key: str = "fec86ba6eb707ed08905757b1bb44b8f",
    opc: str = "C42449363BBAD02B66D16BC975D77CC1",
    model_type: str = "AWGN",
) -> None:
    """UE conf: rfsim **server** with chanmod enabled and one model per DU."""
    out_conf.parent.mkdir(parents=True, exist_ok=True)
    out_conf.write_text(
        "uicc0 = {\n"
        f'  imsi = "{imsi}";\n'
        f'  key = "{key}";\n'
        f'  opc = "{opc}";\n'
        '  pdu_sessions = ({ dnn = "oai"; nssai_sst = 1; });\n'
        "}\n"
        'rfsimulator = ( { serveraddr = "server"; serverport = 4043; '
        'options = ("chanmod"); } );\n'
        + channelmod_block(num_cells, noise_power_db, model_type)
    )


def write_clean_ue_conf(out_conf: Path, imsi: str = "001010000000001") -> None:
    """UE conf with NO channel model: the null-control arm (both cells identical)."""
    out_conf.parent.mkdir(parents=True, exist_ok=True)
    out_conf.write_text(
        "uicc0 = {\n"
        f'  imsi = "{imsi}";\n'
        '  key = "fec86ba6eb707ed08905757b1bb44b8f";\n'
        '  opc = "C42449363BBAD02B66D16BC975D77CC1";\n'
        '  pdu_sessions = ({ dnn = "oai"; nssai_sst = 1; });\n'
        "}\n"
        'rfsimulator = ( { serveraddr = "server"; serverport = 4043; } );\n'
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("channel_dir", help="dir with cfr.npy (and network.json)")
    ap.add_argument("--ue", type=int, required=True, help="UE index to inject")
    ap.add_argument("--cells", default="0,1", help="twin cell indices in DU order")
    ap.add_argument("--taps", type=int, default=DEFAULT_TAPS)
    ap.add_argument("--noise-power-db", type=float, default=-20.0)
    ap.add_argument("--out", default=None, help="output dir (default: channel_dir)")
    args = ap.parse_args()

    d = Path(args.channel_dir)
    out = Path(args.out) if args.out else d
    cfr = np.load(d / "cfr.npy")
    cells = [int(x) for x in args.cells.split(",")]

    taps = out / "oai_rt_taps_multicell.txt"
    diag = write_multicell_taps(taps, cfr, args.ue, cells, num_taps=args.taps)
    conf = out / "ue_multicell.conf"
    write_ue_conf(conf, len(cells), args.noise_power_db)

    print(json.dumps(diag, indent=2))
    print(f"wrote {taps}")
    print(f"wrote {conf}")
    print(f"\nrun the UE with:  OAI_RT_TAPS={taps} ./nr-uesoftmodem ... -O {conf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
