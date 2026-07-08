#!/usr/bin/env python3
"""Rebuild every paper figure as vector PDF from committed data.

No ray tracing, no OAI, no re-running an experiment: this reads only the CSV/JSON
under ``experiments/results/`` and writes ``paper/fig_*.pdf``. That means the paper's
figures can be regenerated (and reviewed for style) in seconds, and a figure can never
silently drift from the numbers in the text.

Vector output with ``pdf.fonttype = 42`` embeds TrueType fonts, which IEEE requires.
Figure widths are set in inches to match a single IEEEtran column (3.5 in).

Run:  python3 experiments/paper_figures.py
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.fig_export import save_figure  # noqa: E402

RESULTS = ROOT / "experiments" / "results"
PAPER = ROOT / "paper"
COL = 3.5           # IEEEtran single-column width, inches

PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9", "#E69F00"]


def _style(plt) -> None:
    from cycler import cycler
    plt.rcParams.update({
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "lines.linewidth": 1.4, "pdf.fonttype": 42, "ps.fonttype": 42,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.prop_cycle": cycler(color=PALETTE),
        "grid.linestyle": ":", "grid.linewidth": 0.6, "axes.axisbelow": True,
        "legend.frameon": False,
        "axes.edgecolor": "#444444", "xtick.color": "#444444", "ytick.color": "#444444",
        "axes.labelcolor": "#222222", "text.color": "#222222",
    })


def _rows(name):
    with open(RESULTS / name) as fh:
        return list(csv.DictReader(fh))


def _json(name):
    p = RESULTS / name
    return json.loads(p.read_text()) if p.exists() else None


# --------------------------------------------------------------------------
def _plot_decision_regret(plt) -> None:
    """Reporting error (what the twin says) vs regret (what acting on it costs)."""
    rows, summary = _rows("decision_regret.csv"), _json("decision_regret.json")
    order = [c for c in ("ideal", "margin2db", "offset", "attenuated") if c in summary["curves"]]
    lab = {"ideal": "Shannon\n(uncalib.)", "margin2db": "$+2$ dB\n(assumed)",
           "offset": "$+\\delta$\n(fitted)", "attenuated": "$a\\cdot$Shan.\n(fitted)"}

    fig, ax = plt.subplots(1, 2, figsize=(COL, 1.85))
    infl = [[float(r["tput_inflation_median_pct"]) for r in rows if r["curve"] == c
             and np.isfinite(float(r["tput_inflation_median_pct"]))] for c in order]
    ax[0].boxplot(infl, tick_labels=[lab[c] for c in order], showmeans=True, widths=0.6,
                  flierprops={"markersize": 2})
    ax[0].axhline(0, color="k", lw=0.9)
    ax[0].set_ylabel("reporting error [%]")
    ax[0].set_title("What the twin says", fontsize=7.5)
    ax[0].grid(True, axis="y", alpha=0.3)

    reg = [[float(r["regret_utility_pts"]) for r in rows if r["curve"] == c] for c in order]
    ax[1].boxplot(reg, tick_labels=[lab[c] for c in order], showmeans=True, widths=0.6,
                  flierprops={"markersize": 2})
    ax[1].axhline(0, color="k", lw=0.9)
    ax[1].set_ylabel("PF utility regret [nats]")
    ax[1].set_title("What acting on it costs", fontsize=7.5)
    ax[1].grid(True, axis="y", alpha=0.3)
    for a in ax:
        a.tick_params(axis="x", labelsize=5.6)
    fig.tight_layout(pad=0.3)
    save_figure(fig, "fig_decision_regret", PAPER, RESULTS)
    plt.close(fig)


def _plot_real_gap(plt) -> None:
    """The twin-to-MAC ratio is constant; the MAC-to-application spread is the emulator."""
    from dtrapp.kpi.link_curve import load_link_curve
    curve = load_link_curve()
    d = _json("real_fidelity_gap.json")
    a = d["abs_link_fidelity"]
    bw = a["bandwidth_mhz"] * 1e6
    cal = [r for r in _rows("real_goodput_calib.csv") if r["dl_mcs"] and r["mac_goodput_mbps"]]

    se = {int(p["mcs"]): p["se_bps_per_hz"] for p in curve.points}
    sin = {int(p["mcs"]): p["sinr_db"] for p in curve.points}
    mcs = sorted(int(r["dl_mcs"]) for r in cal)
    by = {int(r["dl_mcs"]): r for r in cal}
    x = np.array([sin[m] for m in mcs])
    twin = np.array([bw * se[m] * 0.9 / 1e6 for m in mcs])
    tdd = twin * a["dl_duty"]
    mac = np.array([float(by[m]["mac_goodput_mbps"]) for m in mcs])
    app = np.array([float(by[m]["dl_goodput_mbps"]) for m in mcs])

    fig, ax = plt.subplots(1, 2, figsize=(COL, 1.9))
    ax[0].plot(x, twin, "o-", ms=2.6, label="twin $B\\,\\eta_{\\mathrm{OAI}}$")
    ax[0].plot(x, tdd, "^--", ms=2.6, label="$\\times$ TDD duty")
    ax[0].plot(x, mac, "d-.", ms=2.6, label="OAI MAC")
    ax[0].plot(x, app, "s-", ms=2.6, label="application")
    ax[0].set_xlabel("operating SINR [dB]")
    ax[0].set_ylabel("DL rate [Mbps]")
    ax[0].set_title(f"$\\kappa={a['twin_to_mac_derate_mean']:.3f}$ "
                    f"(CV {a['twin_to_mac_derate_cv_pct']:.1f}\\%)", fontsize=7.5)
    ax[0].grid(True, alpha=0.3)
    ax[0].legend(fontsize=5.6, handlelength=1.3, labelspacing=0.2)

    mv = [r for r in _rows("real_fidelity_gap.csv") if int(r["moved"]) and not int(r["outage"])]
    tg = [float(r["twin_gain_pct"]) for r in mv]
    mg = [float(r["mac_gain_pct"]) for r in mv]
    rg = [float(r["real_gain_pct"]) for r in mv]
    lim = max(abs(min(tg + mg + rg)), abs(max(tg + mg + rg))) * 1.08
    ax[1].plot([-lim, lim], [-lim, lim], "k--", lw=0.9, alpha=0.6, label="$y{=}x$")
    ax[1].scatter(tg, mg, marker="d", s=16, zorder=3, color=PALETTE[2],
                  label=f"vs MAC ({d['gap_vs_mac_mean_pts']:+.1f} pts)")
    ax[1].scatter(tg, rg, marker="o", s=16, zorder=3, color=PALETTE[1], alpha=0.85,
                  label=f"vs app ({d['moved_fidelity_gap_median_pts']:+.0f} pts)")
    ax[1].set_xlabel("twin gain [%]")
    ax[1].set_ylabel("delivered gain [%]")
    ax[1].set_title("rApp steering gain", fontsize=7.5)
    ax[1].grid(True, alpha=0.3)
    ax[1].legend(fontsize=5.6, loc="upper left", handlelength=1.3, labelspacing=0.2)
    fig.tight_layout(pad=0.3)
    save_figure(fig, "fig_real_fidelity_gap", PAPER, RESULTS)
    plt.close(fig)


def _plot_null_control(plt) -> None:
    """On two identical cells a correct probe reports no dependence on position."""
    rows, summary = _rows("multignb_null_control.csv"), _json("multignb_null_control.json")
    arms = [a for a in ("cochannel_tcp6", "cochannel_plateau") if a in summary["arms"]]
    short = {"cochannel_tcp6": "original probe", "cochannel_plateau": "plateau probe"}

    fig, ax = plt.subplots(1, 2, figsize=(COL, 1.75))
    for arm, colour in zip(arms, (PALETTE[1], PALETTE[0])):
        for pci, mark in ((0, "o"), (1, "s")):
            pts = [(int(r["pos"]), float(r["goodput_mbps"])) for r in rows
                   if r["arm"] == arm and r["pci"] and int(r["pci"]) == pci and r["goodput_mbps"]]
            if pts:
                ax[0].scatter(*zip(*pts), marker=mark, s=13, alpha=0.8, color=colour,
                              label=f"{short[arm]}, PCI {pci}")
    ax[0].set_xlabel("position in handover sequence")
    ax[0].set_ylabel("DL goodput [Mbps]")
    ax[0].set_title("Identical cells", fontsize=7.5)
    ax[0].grid(True, alpha=0.3)
    ax[0].legend(fontsize=5.2, handlelength=1.0, labelspacing=0.15)

    xs = np.arange(len(arms))
    for i, est in enumerate(("naive_apparent_gain_pct", "balanced_apparent_gain_pct")):
        vals = [summary["arms"][a][est]["mean"] if summary["arms"][a][est] else 0.0 for a in arms]
        errs = [summary["arms"][a][est]["std"] if summary["arms"][a][est] else 0.0 for a in arms]
        ax[1].bar(xs + (i - 0.5) * 0.34, vals, 0.32, yerr=errs, capsize=2,
                  label=("naive" if i == 0 else "reversal"))
    ax[1].axhline(0, color="k", lw=1.0)
    ax[1].set_xticks(xs)
    ax[1].set_xticklabels(["original\nprobe", "plateau\nprobe"], fontsize=6.5)
    ax[1].set_ylabel("apparent cell effect [%]")
    ax[1].set_title("Truth is $0\\%$", fontsize=7.5)
    ax[1].grid(True, axis="y", alpha=0.3)
    ax[1].legend(fontsize=6)
    fig.tight_layout(pad=0.3)
    save_figure(fig, "fig_null_control", PAPER, RESULTS)
    plt.close(fig)


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _style(plt)

    for name, fn in (("decision_regret", _plot_decision_regret),
                     ("real_fidelity_gap", _plot_real_gap),
                     ("null_control", _plot_null_control)):
        try:
            fn(plt)
            print(f"  wrote paper/fig_{name}.pdf", flush=True)
        except FileNotFoundError as e:
            print(f"  skipped fig_{name}: missing {e.filename}", flush=True)

    # The link curve has its own plotting script (it reads the OAI table, not results/).
    lc = ROOT / "oai" / "plot_link_curve.py"
    if lc.exists():
        subprocess.run([sys.executable, str(lc)], check=False)

    print("\npaper figures:")
    for p in sorted(PAPER.glob("fig_*.pdf")):
        print(f"  {p.name}  {p.stat().st_size/1024:.0f} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
