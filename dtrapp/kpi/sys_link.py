"""Full Sionna SYS link-level throughput (stages 4-5).

This is the proper system-level chain for a 5G-NR digital twin:

  1. The ray-traced **channel frequency response** (CFR) per cell -> UE comes from
     Sionna RT (`SionnaPropagationEngine.compute_cfr`).
  2. **Cell association**: each UE attaches to the cell with the strongest average
     received power.
  3. **Post-equalization SINR**: per UE, Sionna's regularized zero-forcing
     precoder (`RZFPrecodedChannel`, beamforming gain from the BS array) plus the
     LMMSE equalizer (`LMMSEPostEqualizationSINR`) turn the serving CFR into a
     post-equalization SINR. Inter-cell interference (full-buffer neighbours) is
     folded into the effective noise per resource element.
  4. **Link adaptation**: `InnerLoopLinkAdaptation` + `PHYAbstraction` pick the
     highest 5G-NR MCS whose BLER stays within `bler_target`, giving a capped
     spectral efficiency `SE = Qm * coderate`.
  5. **Scheduling**: a proportional-fair scheduler shares each cell's airtime
     among its UEs. On a static, full-buffer snapshot PF is provably equal-airtime
     (maximising sum-log-throughput with constant per-UE rates => 1/K each), so we
     allocate `1/K_cell` airtime per UE; the realised goodput is
     `SE * (1 - bler_target)`.

Per-UE throughput   = (B_cell / K_cell) * SE * (1 - bler_target)
Per-cell throughput = sum of its UEs' throughput

Requires Sionna (`pip install sionna`). The import is deferred to call time so the
geometry / network stages and their tests run without Sionna installed.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi
from dtrapp.network.models import Network


def compute_link_level_kpis(
    network: Network, cfr, config: SimulationConfig
) -> KpiResult:
    """Per-UE and per-cell KPIs from the ray-traced CFR via the Sionna SYS chain.

    `cfr` is the torch tensor returned by `SionnaPropagationEngine.compute_cfr`,
    shape [num_ues, num_ue_ant, num_cells, num_bs_ant, num_ofdm_symbols, num_sc].
    """
    try:
        import torch
        from sionna.phy.constants import BOLTZMANN_CONSTANT
        from sionna.phy.mimo import StreamManagement
        from sionna.phy.nr.utils import decode_mcs_index
        from sionna.phy.ofdm import (
            LMMSEPostEqualizationSINR,
            ResourceGrid,
            RZFPrecodedChannel,
        )
        from sionna.phy.utils import db_to_lin, dbm_to_watt
        from sionna.sys import InnerLoopLinkAdaptation, PHYAbstraction
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "Sionna SYS is required for the link-level throughput model. "
            "Install it with `pip install sionna`."
        ) from exc

    cells, ues = network.cells, network.ues
    num_ues, num_cells = len(ues), len(cells)
    if num_ues == 0 or num_cells == 0:
        return KpiResult()

    nU, _, nC, _, num_sym, num_sc = cfr.shape
    scs = float(config.subcarrier_spacing_hz)
    bler_target = float(config.bler_target)
    mcs_table_index = int(config.mcs_table_index)

    # Average channel power per (UE, cell), and received power = Ptx * |h|^2.
    chan_pow = (torch.abs(cfr) ** 2).mean(dim=(1, 3, 4, 5)).cpu().numpy()  # [nU, nC]
    tx_watt = np.array([float(dbm_to_watt(torch.tensor(c.tx_power_dbm))) for c in cells])
    rx_watt = chan_pow * tx_watt[None, :]                                  # [nU, nC]
    serving = rx_watt.argmax(axis=1)

    # Thermal noise per resource element (per subcarrier).
    thermal_re = np.array(
        [float(BOLTZMANN_CONSTANT) * config.temperature_k * scs for _ in ues]
    )

    rg = ResourceGrid(
        num_ofdm_symbols=num_sym, fft_size=num_sc, subcarrier_spacing=scs,
        num_tx=1, num_streams_per_tx=1,
    )
    sm = StreamManagement(np.ones([1, 1]), 1)
    precoder = RZFPrecodedChannel(resource_grid=rg, stream_management=sm)
    lmmse = LMMSEPostEqualizationSINR(resource_grid=rg, stream_management=sm)

    sinr_db = np.zeros(num_ues, dtype=float)
    for u in range(num_ues):
        s = int(serving[u])
        p_re = tx_watt[s] / num_sc                       # serving tx power per RE
        interf_re = float(np.sum(rx_watt[u]) - rx_watt[u, s]) / num_sc
        no_eff = float(thermal_re[u] + interf_re)
        # Serving link CFR -> [batch=1, num_rx=1, num_rx_ant, num_tx=1, num_bs_ant, sym, sc]
        h_s = cfr[u:u + 1, :, s:s + 1, :, :, :].unsqueeze(1)
        tx_power = torch.ones([1, 1, 1, num_sym, num_sc], dtype=h_s.real.dtype) * p_re
        h_eff = precoder(h_s, tx_power=tx_power, alpha=no_eff)
        sinr = lmmse(h_eff, no=no_eff)
        sinr_lin = float(torch.clamp(sinr.mean(), min=1e-12).cpu())
        sinr_db[u] = 10.0 * np.log10(sinr_lin)

    # Link adaptation: highest MCS within the BLER target for each UE's SINR.
    phy_abs = PHYAbstraction()
    illa = InnerLoopLinkAdaptation(phy_abs, bler_target=bler_target)
    mcs_index = illa(
        num_allocated_re=torch.full([num_ues], 1000, dtype=torch.int32),
        sinr_eff=db_to_lin(torch.tensor(sinr_db, dtype=torch.float32)),
        mcs_table_index=mcs_table_index,
        mcs_category=1,  # downlink
        harq_feedback=-torch.ones([num_ues], dtype=torch.int32),
    )
    mod_order, coderate = decode_mcs_index(
        mcs_index, table_index=mcs_table_index, is_pusch=False
    )
    se = (mod_order.to(coderate.dtype) * coderate).cpu().numpy().astype(float)
    se_goodput = se * (1.0 - bler_target)

    # Proportional-fair scheduling on a static full-buffer snapshot == equal
    # airtime among a cell's UEs.
    attached = np.bincount(serving, minlength=num_cells).astype(float)
    bandwidth_hz = np.array([c.bandwidth_hz for c in cells], dtype=float)
    ue_mbps = bandwidth_hz[serving] / attached[serving] * se_goodput / 1e6

    cell_mbps = np.zeros(num_cells, dtype=float)
    np.add.at(cell_mbps, serving, ue_mbps)

    result = KpiResult()
    for u, ue in enumerate(ues):
        result.ues.append(
            UEKpi(
                ue_id=ue.ue_id,
                serving_cell=cells[int(serving[u])].cell_id,
                x=ue.position[0],
                y=ue.position[1],
                sinr_db=float(sinr_db[u]),
                throughput_mbps=float(ue_mbps[u]),
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
