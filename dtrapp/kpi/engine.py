"""High-level KPI engine: Network + ray-traced CFR -> per-UE/per-cell throughput.

Same structure as the Sionna SYS engine, but the SINR->throughput mapping is
supplied by OpenAirInterface's real PHY (see ``dtrapp.kpi.link_curve`` and
``oai/characterize_link.py``) instead of a link-level model. Stages kept on our
side (they are geometry/network, not "the throughput model"):

    1. Association  - each UE attaches to the strongest cell.
    2. SINR         - serving signal (with BS-array beamforming gain) over
                      inter-cell interference + thermal noise, from the RT channel.
    3. Mapping      - SINR -> (MCS, spectral efficiency) via the OAI-measured curve.
    4. Scheduling   - equal-airtime (proportional-fair on a static full-buffer
                      snapshot) sharing of each cell's bandwidth among its UEs.

Per-UE throughput   = (B_cell / K_cell) * SE * (1 - bler_target)
Per-cell throughput = sum of its UEs' throughput
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.kpi.link_curve import LinkCurve, load_link_curve
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi
from dtrapp.network.models import Network

_BOLTZMANN = 1.380649e-23  # J/K


def _to_numpy(cfr):
    return cfr.detach().cpu().numpy() if hasattr(cfr, "detach") else np.asarray(cfr)


def compute_kpis(
    network: Network,
    cfr,
    config: SimulationConfig,
    link_curve: LinkCurve | None = None,
) -> KpiResult:
    """Per-UE and per-cell KPIs from the ray-traced CFR via the OAI link curve.

    ``cfr`` shape: [num_ues, num_ue_ant, num_cells, num_bs_ant, num_ofdm_symbols, num_sc].
    """
    cells, ues = network.cells, network.ues
    if not ues or not cells:
        return KpiResult()

    curve = link_curve if link_curve is not None else load_link_curve()
    bler_target = float(config.bler_target)

    h = _to_numpy(cfr)
    num_cells = len(cells)

    # Mean channel power per (UE, cell) over UE-ant, BS-ant, symbols, subcarriers.
    mean_h2 = (np.abs(h) ** 2).mean(axis=(1, 3, 4, 5))          # [nU, nC]
    tx_watt = np.array([10.0 ** ((c.tx_power_dbm - 30.0) / 10.0) for c in cells])
    n_bs_ant = max(1, config.bs_antenna_rows * config.bs_antenna_cols)

    rx_watt = mean_h2 * tx_watt[None, :]                        # received power [nU, nC]
    serving = rx_watt.argmax(axis=1)

    result = KpiResult()
    attached = np.bincount(serving, minlength=num_cells).astype(int)
    cell_mbps = np.zeros(num_cells, dtype=float)

    for u, ue in enumerate(ues):
        s = int(serving[u])
        bandwidth = float(cells[s].bandwidth_hz)
        nf_lin = 10.0 ** (float(ue.noise_figure_db) / 10.0)
        noise = _BOLTZMANN * float(config.temperature_k) * bandwidth * nf_lin

        signal = rx_watt[u, s] * n_bs_ant                       # beamforming array gain
        interference = float(rx_watt[u].sum() - rx_watt[u, s])  # other cells, no beam gain
        sinr_lin = signal / max(interference + noise, 1e-30)
        sinr_db = 10.0 * np.log10(max(sinr_lin, 1e-12))

        mcs, se = curve.map_sinr(sinr_db)
        se_goodput = se * (1.0 - bler_target)
        ue_mbps = bandwidth / max(attached[s], 1) * se_goodput / 1e6
        cell_mbps[s] += ue_mbps

        result.ues.append(
            UEKpi(
                ue_id=ue.ue_id,
                serving_cell=cells[s].cell_id,
                x=ue.position[0],
                y=ue.position[1],
                sinr_db=float(sinr_db),
                mcs=int(mcs),
                throughput_mbps=float(ue_mbps),
            )
        )

    for c, cell in enumerate(cells):
        result.cells.append(
            CellKpi(
                cell_id=cell.cell_id,
                num_attached=int(attached[c]),
                throughput_mbps=float(cell_mbps[c]),
            )
        )
    return result
