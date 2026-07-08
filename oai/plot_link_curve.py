#!/usr/bin/env python3
"""Plot the OAI-measured link curve vs the Shannon bound and a Shannon-optimal
(no-implementation-loss) staircase, shading the implementation loss.

Reads ``oai/sinr_throughput_table.json`` (produced by sweeping OAI ``nr_dlsim``)
and writes ``paper/fig_link_curve.pdf`` (and a copy under experiments/results).
Reproduces the figure behind the paper's implementation-loss claims.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    data = json.loads((ROOT / "oai" / "sinr_throughput_table.json").read_text())
    pts = data["points"]
    sinr = np.array([p["sinr_db"] for p in pts], float)
    se = np.array([p["se_bps_per_hz"] for p in pts], float)

    # Shannon bound over the measured SINR range
    x = np.linspace(sinr.min() - 1, sinr.max() + 1, 400)
    shannon = np.log2(1 + 10 ** (x / 10))
    # Shannon-optimal ("idealized") placement of each measured SE: the SINR at
    # which an ideal receiver would already achieve that SE (no impl. loss).
    sinr_ideal = 10 * np.log10(np.maximum(2 ** se - 1, 1e-9))

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(x, shannon, "--", color="0.4", lw=2, label="Shannon bound")
    ax.step(sinr_ideal, se, where="post", color="tab:green", lw=1.3, ls=":",
            label="Idealized staircase (Shannon-optimal)")
    ax.step(sinr, se, where="post", color="tab:blue", lw=2, label="OAI-measured $\\Phi_{\\mathrm{OAI}}$")
    ax.plot(sinr, se, "o", color="tab:blue", ms=3)

    # shade the implementation loss between OAI-measured SE and Shannon
    shannon_at = np.log2(1 + 10 ** (sinr / 10))
    ax.fill_between(sinr, se, shannon_at, step="post", color="tab:red", alpha=0.15,
                    label="Implementation loss")

    # annotate the 10 dB operating point
    se10 = float(se[np.isclose(sinr, 10.0)][0]); sh10 = float(np.log2(1 + 10))
    ax.plot([10, 10], [se10, sh10], color="tab:red", lw=1.2)
    ax.annotate(f"{100*(sh10-se10)/sh10:.0f}% loss\n@10 dB",
                xy=(10, (se10 + sh10) / 2), xytext=(11.5, 2.0),
                fontsize=9, color="tab:red",
                arrowprops=dict(arrowstyle="->", color="tab:red", lw=1))

    # annotate the non-uniform QPSK->16QAM boundary (MCS 9 -> 10)
    s9 = float(sinr[[p["mcs"] for p in pts].index(9)])
    s10 = float(sinr[[p["mcs"] for p in pts].index(10)])
    ax.annotate(f"QPSK$\\to$16QAM:\n{s10-s9:.1f} dB step",
                xy=((s9 + s10) / 2, 1.35), xytext=(2.0, 4.2), fontsize=9,
                arrowprops=dict(arrowstyle="->", lw=1))

    ax.set_xlabel("effective SINR [dB]")
    ax.set_ylabel("spectral efficiency [bits/s/Hz]")
    ax.set_title("OAI-measured link curve vs. Shannon bound")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)
    ax.set_xlim(sinr.min() - 1, sinr.max() + 1)
    ax.set_ylim(0, shannon.max() + 0.3)
    fig.tight_layout()

    sys.path.insert(0, str(ROOT))
    from experiments.fig_export import save_figure

    save_figure(fig, "fig_link_curve", ROOT / "paper", ROOT / "experiments" / "results")
    plt.close(fig)
    print(f"@10dB: OAI={se10:.3f} Shannon={sh10:.3f} loss={100*(sh10-se10)/sh10:.1f}%")
    print(f"QPSK->16QAM step: {s10-s9:.1f} dB")
    print("wrote paper/fig_link_curve.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
