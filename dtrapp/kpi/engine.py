"""High-level KPI engine: Network + ray-traced CFR -> per-UE/per-cell throughput.

Same structure as the Sionna SYS engine, but the SINR->throughput mapping is
supplied by OpenAirInterface's real PHY (see ``dtrapp.kpi.link_curve`` and
``oai/characterize_link.py``) instead of a link-level model. Stages kept on our
side (they are geometry/network, not "the throughput model"):

    1. Association  - each UE attaches to the strongest cell (wideband RSRP).
    2. SINR         - per resource element (OFDM symbol x subcarrier):
                      serving signal with channel-dependent MRT/MRC beamforming
                      over (load-scaled inter-cell interference + thermal noise).
    3. Effective SINR - the per-RE SINR vector is compressed to one AWGN-
                      equivalent SINR per candidate MCS with EESM, so frequency
                      selectivity survives into the link mapping.
    4. Mapping      - effective SINR -> (MCS, spectral efficiency) via the
                      OAI-measured curve (AWGN-referenced, hence EESM).
    5. Scheduling   - equal-airtime (proportional-fair on a static full-buffer
                      snapshot) sharing of each cell's bandwidth among its UEs.

Per-UE throughput   = (B_cell / K_cell) * SE * (1 - bler_target)
Per-cell throughput = sum of its UEs' throughput

Modelling notes (deliberate, stated assumptions):

* Beamforming: each cell serves one UE at a time (TDM airtime share), so the
  optimal single-stream precoder is MRT (matched filter); RZF reduces to MRT
  for a single served stream. Serving-link gain per RE is sigma_max(H_k)^2 -
  coherent, channel-dependent - instead of a flat 10*log10(N_ant) bonus.
* Interference-as-noise: an interfering cell beamforms towards *its own* UE,
  which from the victim's perspective is a random beam; its expected received
  power is ||H_k||_F^2 / N_tx per RE. ``neighbor_load`` (0..1) scales it for
  partially loaded neighbours (1.0 = full-buffer worst case).
* EESM betas are literature values per modulation order; ``eesm_beta_scale``
  is the one-parameter calibration knob to fit against ground-truth (OAI
  in-the-loop) measurements.
"""

from __future__ import annotations

import numpy as np

from dtrapp.config import SimulationConfig
from dtrapp.kpi.link_curve import LinkCurve, load_link_curve
from dtrapp.kpi.results import CellKpi, KpiResult, UEKpi
from dtrapp.network.models import Network

_BOLTZMANN = 1.380649e-23  # J/K

# EESM beta per modulation order (literature values for LTE/NR link abstraction;
# QPSK ~1.5-2, 16QAM ~4-7, 64QAM ~15-25, 256QAM ~28). Calibratable via
# ``config.eesm_beta_scale`` against OAI ground-truth runs.
EESM_BETA_BY_QM = {2: 1.6, 4: 5.0, 6: 18.0, 8: 28.0}


def _to_numpy(cfr):
    return cfr.detach().cpu().numpy() if hasattr(cfr, "detach") else np.asarray(cfr)


def _qm_for_mcs(mcs: int, table_index: int) -> int:
    """Modulation order for a 5G-NR MCS index (38.214 tables 5.1.3.1-1/2)."""
    if table_index == 2:  # up to 256QAM
        if mcs <= 4:
            return 2
        if mcs <= 10:
            return 4
        if mcs <= 19:
            return 6
        return 8
    # table 1: up to 64QAM
    if mcs <= 9:
        return 2
    if mcs <= 16:
        return 4
    return 6


def _eesm_eff_sinr_lin(gamma_lin: np.ndarray, beta: float) -> float:
    """EESM: gamma_eff = -beta * ln(mean(exp(-gamma/beta))), computed stably.

    Uses a log-sum-exp so very high per-RE SINRs don't underflow to exp(-inf).
    """
    x = -gamma_lin / beta
    m = float(x.max())
    lse = m + float(np.log(np.exp(x - m).sum()))
    return float(-beta * (lse - np.log(x.size)))


def _select_mcs_eesm(
    curve: LinkCurve, gamma_lin: np.ndarray, table_index: int, beta_scale: float
) -> tuple[int, float, float]:
    """Highest MCS whose EESM effective SINR meets the curve's required SINR.

    Returns (mcs, se, effective_sinr_db). EESM's beta depends on the candidate
    MCS's modulation order, so the effective SINR is recomputed per candidate.
    """
    for p in sorted(curve.points, key=lambda q: q["sinr_db"], reverse=True):
        beta = EESM_BETA_BY_QM[_qm_for_mcs(int(p["mcs"]), table_index)] * beta_scale
        eff_db = 10.0 * np.log10(max(_eesm_eff_sinr_lin(gamma_lin, beta), 1e-12))
        if eff_db >= p["sinr_db"]:
            return int(p["mcs"]), float(p["se_bps_per_hz"]), float(eff_db)
    # No MCS sustainable: report the effective SINR at the most robust beta.
    beta = EESM_BETA_BY_QM[2] * beta_scale
    eff_db = 10.0 * np.log10(max(_eesm_eff_sinr_lin(gamma_lin, beta), 1e-12))
    return -1, 0.0, float(eff_db)


def _serving_gain_per_re(h_link: np.ndarray) -> np.ndarray:
    """MRT/MRC single-stream beamforming gain sigma_max(H_k)^2 per RE.

    ``h_link`` shape: [num_ue_ant, num_bs_ant, num_sym, num_sc]. Returns
    [num_re] with num_re = num_sym * num_sc.
    """
    n_rx, n_tx, n_sym, n_sc = h_link.shape
    h_re = h_link.transpose(2, 3, 0, 1).reshape(n_sym * n_sc, n_rx, n_tx)
    if n_rx == 1:  # sigma_max == vector norm; skip the SVD
        return (np.abs(h_re[:, 0, :]) ** 2).sum(axis=-1)
    sigma = np.linalg.svd(h_re, compute_uv=False)
    return sigma[:, 0] ** 2


def compute_kpis(
    network: Network,
    cfr,
    config: SimulationConfig,
    link_curve: LinkCurve | None = None,
    cio_db=None,
) -> KpiResult:
    """Per-UE and per-cell KPIs from the ray-traced CFR via the OAI link curve.

    ``cfr`` shape: [num_ues, num_ue_ant, num_cells, num_bs_ant, num_ofdm_symbols, num_sc].

    ``cio_db`` is an optional per-cell cell-individual-offset (dB, length num_cells)
    that biases *association only* (a UE attaches to the cell maximising
    ``RSRP + CIO``). It does not change transmit power or the physical SINR - this
    is the standard O-RAN traffic-steering / load-balancing control knob. Default
    (``None``) reproduces plain strongest-cell association.
    """
    cells, ues = network.cells, network.ues
    if not ues or not cells:
        return KpiResult()

    curve = link_curve if link_curve is not None else load_link_curve()
    bler_target = float(config.bler_target)
    scs = float(config.subcarrier_spacing_hz)
    load = float(np.clip(config.neighbor_load, 0.0, 1.0))
    beta_scale = float(config.eesm_beta_scale)
    table_index = int(config.mcs_table_index)

    h = _to_numpy(cfr)
    num_cells = len(cells)
    n_bs_ant = h.shape[3]

    tx_watt = np.array([10.0 ** ((c.tx_power_dbm - 30.0) / 10.0) for c in cells])
    bw = np.array([float(c.bandwidth_hz) for c in cells])
    # Flat PSD: per-subcarrier tx power = P_total * (scs / cell bandwidth).
    p_re = tx_watt * scs / bw                                    # [nC]

    # Association on wideband mean received power (RSRP-like), biased by the
    # per-cell CIO (traffic-steering control). Power/SINR use the true rx_watt.
    mean_h2 = (np.abs(h) ** 2).mean(axis=(1, 3, 4, 5))           # [nU, nC]
    rx_watt = mean_h2 * tx_watt[None, :]
    if cio_db is None:
        assoc_metric = rx_watt
    else:
        cio = np.asarray(cio_db, dtype=float).reshape(1, num_cells)
        assoc_metric = rx_watt * 10.0 ** (cio / 10.0)
    serving = assoc_metric.argmax(axis=1)

    result = KpiResult()
    attached = np.bincount(serving, minlength=num_cells).astype(int)
    cell_mbps = np.zeros(num_cells, dtype=float)

    for u, ue in enumerate(ues):
        s = int(serving[u])
        bandwidth = float(cells[s].bandwidth_hz)
        nf_lin = 10.0 ** (float(ue.noise_figure_db) / 10.0)
        noise_re = _BOLTZMANN * float(config.temperature_k) * scs * nf_lin

        # Serving signal per RE: coherent MRT/MRC beamforming on the actual channel.
        signal_re = p_re[s] * _serving_gain_per_re(h[u, :, s])   # [nRE]

        # Inter-cell interference per RE: expected random-beam power, load-scaled.
        fro2 = (np.abs(h[u]) ** 2).sum(axis=(0, 2))              # [nC, nSym, nSC]
        fro2_re = fro2.reshape(num_cells, -1)                    # [nC, nRE]
        mask = np.ones(num_cells, dtype=bool)
        mask[s] = False
        interf_re = load * (
            (p_re[mask, None] / n_bs_ant) * fro2_re[mask]
        ).sum(axis=0)                                            # [nRE]

        gamma_lin = signal_re / np.maximum(interf_re + noise_re, 1e-30)
        mcs, se, eff_sinr_db = _select_mcs_eesm(curve, gamma_lin, table_index, beta_scale)

        se_goodput = se * (1.0 - bler_target)
        ue_mbps = bandwidth / max(attached[s], 1) * se_goodput / 1e6
        cell_mbps[s] += ue_mbps

        result.ues.append(
            UEKpi(
                ue_id=ue.ue_id,
                serving_cell=cells[s].cell_id,
                x=ue.position[0],
                y=ue.position[1],
                sinr_db=float(eff_sinr_db),
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
