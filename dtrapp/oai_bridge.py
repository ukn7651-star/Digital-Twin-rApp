"""Bridge the analytical multi-cell twin to a single-link OAI stack.

A live OAI rfsimulator link is single-cell: it has no notion of the other cells
a UE hears. This module computes, per UE, the inter-cell interference the twin
predicts and expresses it as the amount by which that UE's **noise floor** should
be raised in OAI, so a single-link OAI run "feels" the multi-cell network it
belongs to (the interference-as-noise-floor trick).

The quantity written is an *interference rise* relative to thermal noise:

    rise_dB = 10 * log10((I + N_thermal) / N_thermal)

where ``I`` is the (load-scaled) sum of the non-serving cells' received power and
``N_thermal = k*T*B*NF``. In OAI's channel model, the AWGN level is set by
``noise_power_dB`` relative to the signal scale, so the site-specific value to use
is ``noise_power_dB = baseline_noise_power_dB + rise_dB`` per UE (client), where
``baseline_noise_power_dB`` is the interference-free level you calibrate once on
your host. The association (serving cell) matches the twin's KPI engine.

This is pure NumPy and is unit-tested; the OAI-side scripts that consume the
generated config are validated on a full host (see ``oai/README_full_stack.md``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.network.models import Network

_BOLTZMANN = 1.380649e-23  # J/K


@dataclass
class UEFloor:
    ue_id: str
    serving_cell: str
    thermal_dbm: float
    interference_dbm: float
    rise_db: float          # 10log10((I+N)/N): noise-floor rise from other cells
    wideband_sinr_db: float  # informational (wideband RSRP/(I+N))


def _to_numpy(cfr):
    return cfr.detach().cpu().numpy() if hasattr(cfr, "detach") else np.asarray(cfr)


def _w_to_dbm(w: float) -> float:
    return 10.0 * np.log10(max(w, 1e-30) / 1e-3)


def per_ue_interference_floor(
    network: Network, cfr, config: SimulationConfig
) -> list[UEFloor]:
    """Per-UE inter-cell interference expressed as a noise-floor rise (dB).

    Uses the same wideband association as the KPI engine (strongest mean received
    power) and the same ``neighbor_load`` scaling of interference.
    """
    cells, ues = network.cells, network.ues
    if not cells or not ues:
        return []

    load = float(np.clip(config.neighbor_load, 0.0, 1.0))
    h = _to_numpy(cfr)
    mean_h2 = (np.abs(h) ** 2).mean(axis=(1, 3, 4, 5))            # [nU, nC]
    tx_watt = np.array([10.0 ** ((c.tx_power_dbm - 30.0) / 10.0) for c in cells])
    rx_watt = mean_h2 * tx_watt[None, :]                          # [nU, nC]
    serving = rx_watt.argmax(axis=1)

    floors: list[UEFloor] = []
    for u, ue in enumerate(ues):
        s = int(serving[u])
        bw = float(cells[s].bandwidth_hz)
        nf_lin = 10.0 ** (float(ue.noise_figure_db) / 10.0)
        thermal = _BOLTZMANN * float(config.temperature_k) * bw * nf_lin
        interference = load * float(rx_watt[u].sum() - rx_watt[u, s])
        rise_db = 10.0 * np.log10((interference + thermal) / thermal)
        sinr_db = 10.0 * np.log10(max(rx_watt[u, s], 1e-30) / (interference + thermal))
        floors.append(
            UEFloor(
                ue_id=ue.ue_id,
                serving_cell=cells[s].cell_id,
                thermal_dbm=_w_to_dbm(thermal),
                interference_dbm=_w_to_dbm(interference),
                rise_db=float(rise_db),
                wideband_sinr_db=float(sinr_db),
            )
        )
    return floors


def _channelmod_block(models: list[tuple[str, float]], model_type: str = "AWGN") -> str:
    """OAI channelmod block with one model per (name, noise_power_dB)."""
    entries = ",\n".join(
        f'    {{ model_name = "{name}"; type = "{model_type}"; ploss_dB = 0.0; '
        f"noise_power_dB = {npow:.2f}; forgetfact = 0; offset = 0; }}"
        for name, npow in models
    )
    return (
        "channelmod = {\n"
        f"  max_chan = {max(len(models) + 1, 10)};\n"
        '  modellist = "modellist_rfsimu_1";\n'
        "  modellist_rfsimu_1 = (\n"
        f"{entries}\n"
        "  );\n"
        "};\n"
    )


def write_per_ue_noise_configs(
    floors: list[UEFloor],
    out_path,
    baseline_noise_power_db: float = -50.0,
    model_type: str = "AWGN",
) -> str:
    """Write an OAI channelmod snippet with a per-client model per UE.

    Each UE (client) ``rfsimu_channel_ue{i}`` gets ``noise_power_dB =
    baseline + rise_db``, so its emulated noise floor reflects the twin's
    inter-cell interference. Returns the written text.
    """
    models = [
        (f"rfsimu_channel_ue{i}", baseline_noise_power_db + f.rise_db)
        for i, f in enumerate(floors)
    ]
    text = _channelmod_block(models, model_type)
    with open(out_path, "w") as fh:
        fh.write(text)
    return text


def floors_to_rows(floors: list[UEFloor]) -> list[dict]:
    return [asdict(f) for f in floors]
