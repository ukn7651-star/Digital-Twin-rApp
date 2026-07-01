"""OAI-derived SINR -> (MCS, spectral efficiency) mapping.

This is the piece that *replaces* the Sionna SYS throughput model: instead of a
formula, the SINR->rate curve is measured by OpenAirInterface's real PHY
(`nr_dlsim` sweeps SNR x MCS and reports BLER). ``oai/characterize_link.py``
turns that sweep into ``oai/sinr_throughput_table.json``; this module loads it and
maps each UE's SINR to the highest MCS whose BLER stays within the target.

The engine uses the OAI table when present. A coarse built-in fallback (NOT
OAI-measured, clearly flagged) keeps the pipeline runnable without OAI so tests
and the geometry/network stages don't require a built OAI.
"""

from __future__ import annotations

import json
from pathlib import Path

# Default location of the OAI-measured table (committed once generated).
DEFAULT_TABLE_PATH = Path(__file__).resolve().parents[2] / "oai" / "sinr_throughput_table.json"

# Fallback staircase: required SINR (dB) -> (MCS index, SE = Qm*coderate) for
# 5G-NR MCS table 1 at ~10% BLER in AWGN. Coarse anchors only; replace with the
# OAI-measured table for real numbers.
_FALLBACK = {
    "source": "built-in fallback (NOT OAI-measured)",
    "bler_target": 0.1,
    "mcs_table_index": 1,
    "points": [
        {"sinr_db": -6.0, "mcs": 0, "se_bps_per_hz": 0.2344},
        {"sinr_db": -4.0, "mcs": 2, "se_bps_per_hz": 0.3770},
        {"sinr_db": -2.0, "mcs": 4, "se_bps_per_hz": 0.6016},
        {"sinr_db": 0.0, "mcs": 6, "se_bps_per_hz": 0.8770},
        {"sinr_db": 2.0, "mcs": 9, "se_bps_per_hz": 1.4766},
        {"sinr_db": 5.0, "mcs": 12, "se_bps_per_hz": 1.9141},
        {"sinr_db": 8.0, "mcs": 16, "se_bps_per_hz": 2.7305},
        {"sinr_db": 11.0, "mcs": 19, "se_bps_per_hz": 3.6094},
        {"sinr_db": 14.0, "mcs": 22, "se_bps_per_hz": 4.5234},
        {"sinr_db": 17.0, "mcs": 25, "se_bps_per_hz": 5.5547},
        {"sinr_db": 20.0, "mcs": 27, "se_bps_per_hz": 6.2266},
        {"sinr_db": 23.0, "mcs": 28, "se_bps_per_hz": 6.9141},
    ],
}


class LinkCurve:
    """Maps SINR (dB) -> (MCS, spectral efficiency in bits/s/Hz)."""

    def __init__(self, data: dict):
        self.source = data.get("source", "unknown")
        self.bler_target = float(data.get("bler_target", 0.1))
        self.mcs_table_index = int(data.get("mcs_table_index", 1))
        self.is_oai = "oai" in self.source.lower() or "dlsim" in self.source.lower()
        # Sorted by required SINR ascending.
        self.points = sorted(data["points"], key=lambda p: p["sinr_db"])

    def map_sinr(self, sinr_db: float) -> tuple[int, float]:
        """Highest MCS/SE sustainable at ``sinr_db`` (0 if below the lowest point)."""
        mcs, se = -1, 0.0
        for p in self.points:
            if sinr_db >= p["sinr_db"]:
                mcs, se = int(p["mcs"]), float(p["se_bps_per_hz"])
            else:
                break
        return mcs, se


def load_link_curve(path: str | Path | None = None) -> LinkCurve:
    """Load the OAI-measured table if available, else the flagged fallback."""
    p = Path(path) if path is not None else DEFAULT_TABLE_PATH
    if p.exists():
        return LinkCurve(json.loads(p.read_text()))
    return LinkCurve(_FALLBACK)
