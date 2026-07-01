"""Export the ray-traced channel + network so OpenAirInterface can run over it.

Writes two files under ``<output_dir>/channel/``:
  - ``network.json`` — cells and UEs (positions, radio config, traffic demand).
  - ``cfr.npy``      — the complex channel frequency response tensor, shape
                       [num_ues, num_ue_ant, num_cells, num_bs_ant, num_ofdm_symbols, num_sc].

The OAI side (see ``oai/cfr_to_oai_channel.py``) consumes these to drive the
rfsimulator's channel with our site-specific ray-traced channel.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from dtrapp.network.models import Network


def export_channel(network: Network, cfr, out_dir) -> list[Path]:
    d = Path(out_dir) / "channel"
    d.mkdir(parents=True, exist_ok=True)

    net = {
        "cells": [
            {
                "cell_id": c.cell_id,
                "position": list(c.position),
                "azimuth_deg": c.azimuth_deg,
                "tx_power_dbm": c.tx_power_dbm,
                "carrier_freq_hz": c.carrier_freq_hz,
                "bandwidth_hz": c.bandwidth_hz,
            }
            for c in network.cells
        ],
        "ues": [
            {
                "ue_id": u.ue_id,
                "position": list(u.position),
                "traffic_demand_mbps": u.traffic_demand_mbps,
                "noise_figure_db": u.noise_figure_db,
            }
            for u in network.ues
        ],
    }
    net_path = d / "network.json"
    net_path.write_text(json.dumps(net, indent=2))

    # cfr is a (complex) torch tensor from Sionna RT; store as a numpy .npy.
    arr = cfr.detach().cpu().numpy() if hasattr(cfr, "detach") else np.asarray(cfr)
    cfr_path = d / "cfr.npy"
    np.save(cfr_path, arr)

    return [net_path, cfr_path]
