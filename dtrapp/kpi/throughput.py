"""SINR -> downlink throughput via Sionna SYS link adaptation (stage 5).

Instead of the analytic Shannon bound, this uses Sionna SYS's link-to-system
abstraction, which is the realistic 5G-NR way to turn SINR into a data rate:

  * ``InnerLoopLinkAdaptation`` selects, for each UE's effective SINR, the
    highest 5G-NR MCS whose block error rate (BLER) stays within ``bler_target``.
    It uses ``PHYAbstraction`` (NR BLER tables) internally.
  * the selected MCS gives a capped spectral efficiency  SE = Qm x coderate
    [bit/s/Hz] (so it never exceeds the modulation ceiling, unlike Shannon);
  * link adaptation holds the BLER at the target, so the expected goodput is
    SE x (1 - bler_target).

Per-UE throughput   = (B_cell / K_cell) * SE * (1 - bler_target)   [bit/s]
Per-cell throughput = sum of its UEs' throughput

Each cell still shares its bandwidth equally among its attached UEs (same sharing
rule as the Shannon baseline). This is the single place where the throughput
model lives; swapping it does not touch the SINR or runner layers.

Requires Sionna SYS (``pip install sionna``). The import is deferred to call
time so the rest of the pipeline (and its tests) run without Sionna installed.
"""

from __future__ import annotations

import numpy as np

# Nominal number of allocated resource elements used when querying the MCS
# selector. It only affects transport-block sizing inside the BLER lookup; the
# spectral efficiency of the chosen MCS is what we turn into a rate.
_NOMINAL_ALLOCATED_RE = 1000


def link_adapted_throughput(sinr_db, serving, bandwidth_hz, num_cells, config):
    """Per-UE and per-cell downlink throughput in Mbps via Sionna SYS.

    sinr_db: (num_ues,)  serving: (num_ues,) cell index  bandwidth_hz: (num_cells,)
    config: provides ``bler_target`` and ``mcs_table_index``.
    Returns (ue_mbps (num_ues,), cell_mbps (num_cells,)).
    """
    serving = np.asarray(serving)
    bandwidth_hz = np.asarray(bandwidth_hz, dtype=float)
    se = _spectral_efficiency_la(np.asarray(sinr_db, dtype=float), config)

    attached = np.bincount(serving, minlength=num_cells).astype(float)
    ue_mbps = bandwidth_hz[serving] / attached[serving] * se / 1e6

    cell_mbps = np.zeros(num_cells, dtype=float)
    np.add.at(cell_mbps, serving, ue_mbps)
    return ue_mbps, cell_mbps


def _spectral_efficiency_la(sinr_db: np.ndarray, config) -> np.ndarray:
    """Per-UE goodput spectral efficiency (bit/s/Hz) from Sionna SYS link adaptation."""
    num_ues = int(sinr_db.shape[0])
    if num_ues == 0:
        return np.zeros(0, dtype=float)

    try:
        import torch
        from sionna.phy.nr.utils import decode_mcs_index
        from sionna.phy.utils import db_to_lin
        from sionna.sys import InnerLoopLinkAdaptation, PHYAbstraction
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "Sionna SYS is required for the throughput model. "
            "Install it with `pip install sionna`."
        ) from exc

    bler_target = float(config.bler_target)
    mcs_table_index = int(config.mcs_table_index)

    phy_abs = PHYAbstraction()
    illa = InnerLoopLinkAdaptation(phy_abs, bler_target=bler_target)

    # Select, per UE, the highest MCS whose BLER stays within the target for the
    # UE's effective SINR. harq_feedback = -1 marks "no prior feedback" (ILLA does
    # not use it; it relies purely on the SINR estimate).
    sinr_eff = db_to_lin(torch.tensor(sinr_db, dtype=torch.float32))
    num_allocated_re = torch.full([num_ues], _NOMINAL_ALLOCATED_RE, dtype=torch.int32)
    harq_feedback = -torch.ones([num_ues], dtype=torch.int32)

    mcs_index = illa(
        num_allocated_re=num_allocated_re,
        sinr_eff=sinr_eff,
        mcs_table_index=mcs_table_index,
        mcs_category=1,  # downlink
        harq_feedback=harq_feedback,
    )

    mod_order, coderate = decode_mcs_index(
        mcs_index, table_index=mcs_table_index, is_pusch=False
    )
    se = (mod_order.to(coderate.dtype) * coderate).cpu().numpy().astype(float)
    return se * (1.0 - bler_target)
