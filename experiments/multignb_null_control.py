#!/usr/bin/env python3
"""Null control: what does the multi-cell harness report when there is nothing to report?

The first multi-cell experiment concluded that the twin's per-UE steering gain (66%)
overshot the delivered gain (9.0%) by 57+/-165 points, and attributed the spread to
the DUs' clean channel. Before believing any of that, ask what the harness reports
when the two cells are *identical*: the true cell effect is then exactly zero, so
whatever comes out is instrument bias.

Four arms decompose the original number along two axes -- the *timing* of the probe (a
6 s TCP flow started 3 s after the handover, as originally used, vs a 20 s flow after a
20 s settle, by which point TCP has left slow start) and the *cells* (the stock ``pci1``
DU conf, on a different carrier -- 3649.44 vs 3450.72 MHz -- with a different SSB burst
position, vs a co-channel DU1 identical to DU0 except PCI/cell-id):

  cochannel_tcp6     - the true null control: two physically identical cells, original
                       instrument. Everything it reports is instrument bias.
  cochannel_plateau  - two identical cells, probe at TCP's plateau. Should read ~0.
  difffreq_tcp6      - the original harness, verbatim.
  difffreq_plateau   - plateau probe on the original two cells: isolates how much of the
                       bias comes from the DU configs differing.

A saturating UDP probe would be the textbook capacity instrument, and an earlier version
of this file used one. It is invalid here: in reverse mode iperf3 reports the *sending*
rate, so an 8 Mbps offer through a 10 Mbps MAC reads exactly 8.00 Mbps and a 20 Mbps offer
reads exactly 20.00 Mbps, both with ~0% loss. See ``experiments/oai_multicell_stack.py``.

Two estimators are reported for every arm:

  naive    - the original: (pos 2, always PCI1) vs (pos 1, always PCI0). Measurement
             order and cell identity are perfectly confounded.
  balanced - drop the single pre-handover point and average each cell over the
             remaining positions, which carry equal mean sequence position (4.0 for
             n=6), so a drift in sequence position cancels to first order.

Outputs: experiments/results/multignb_null_control.{csv,json}

Prereqs: 5G core healthy, OAI built with telnetsrv, host READY (oai/check_host.sh).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.oai_multicell_stack import (
    RUN,
    Stack,
    balanced_cell_means,
    ensure_iperf_server,
    reversal_sequence,
)
from oai.cfr_to_oai_multicell import write_clean_ue_conf

# arm -> (DU1 conf, iperf seconds, settle seconds)
ARMS = {
    "cochannel_tcp6": ("cochannel", 6, 3),        # identical cells, original instrument
    "cochannel_plateau": ("cochannel", 20, 20),   # identical cells, probe at TCP's plateau
    "difffreq_tcp6": ("difffreq", 6, 3),          # the original harness, verbatim
    "difffreq_plateau": ("difffreq", 20, 20),
}
# Default reps per arm. The tcp6 arms leave the link in a collapsed state (MCS 0-7), so
# each of their flows takes minutes; the drift they show is unambiguous with few reps.
DEFAULT_REPS = {"cochannel_tcp6": 3, "cochannel_plateau": 3,
                "difffreq_tcp6": 1, "difffreq_plateau": 2}


def _pct(new, old) -> float:
    if not new or not old or old <= 0:
        return float("nan")
    return 100.0 * (new - old) / old


def run_rep(arm: str, rep: int, n: int) -> list[dict]:
    variant, dur, settle = ARMS[arm]
    tag = f"null_{arm}_r{rep}"
    conf = RUN / f"ue_{tag}.conf"
    write_clean_ue_conf(conf)
    stack = Stack(tag=tag, ue_conf=conf, taps=None, cochannel=(variant == "cochannel"))
    try:
        stack.start()
        rows = reversal_sequence(stack, n=n, dur=dur, settle=settle)
    finally:
        stack.stop()
    for r in rows:
        r |= {"arm": arm, "variant": variant, "dur_s": dur, "settle_s": settle, "rep": rep}
    return rows


def _stat(v) -> dict | None:
    a = np.array([x for x in v if x == x], float)
    if not a.size:
        return None
    return {"mean": round(float(a.mean()), 3),
            "std": round(float(a.std(ddof=1)) if a.size > 1 else 0.0, 3),
            "n": int(a.size)}


def summarize(all_rows: list[dict]) -> dict:
    out: dict = {
        "premise": "both cells carry the same clean channel, so the true cell effect is 0; "
                   "any non-zero apparent gain is instrument bias",
        "arms": {},
    }
    for arm in [a for a in ARMS if any(r["arm"] == a for r in all_rows)]:
        naive, balanced, pos_means, mcs_by_pci = [], [], {}, {0: [], 1: []}
        for rep in sorted({r["rep"] for r in all_rows if r["arm"] == arm}):
            rows = [r for r in all_rows
                    if r["arm"] == arm and r["rep"] == rep and r["goodput_mbps"] is not None]
            by_pos = {r["pos"]: r for r in rows}
            if 1 in by_pos and 2 in by_pos:
                naive.append(_pct(by_pos[2]["goodput_mbps"], by_pos[1]["goodput_mbps"]))
            b = balanced_cell_means(rows)
            balanced.append(_pct(b["g_pci1_mbps"], b["g_pci0_mbps"]))
            for r in rows:
                pos_means.setdefault(r["pos"], []).append(r["goodput_mbps"])
                if r["dl_mcs"] is not None:
                    mcs_by_pci[r["pci"]].append(r["dl_mcs"])
        out["arms"][arm] = {
            "naive_apparent_gain_pct": _stat(naive),
            "balanced_apparent_gain_pct": _stat(balanced),
            "goodput_by_position_mbps": {str(p): round(float(np.mean(v)), 3)
                                         for p, v in sorted(pos_means.items())},
            "mean_dl_mcs_pci0": round(float(np.mean(mcs_by_pci[0])), 2) if mcs_by_pci[0] else None,
            "mean_dl_mcs_pci1": round(float(np.mean(mcs_by_pci[1])), 2) if mcs_by_pci[1] else None,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=None,
                    help="override the per-arm default rep count")
    ap.add_argument("--n", type=int, default=6, help="measurements per reversal sequence")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--append", action="store_true",
                    help="merge into the existing CSV instead of overwriting")
    ap.add_argument("--out", default="experiments/results")
    ap.add_argument("--fig", default="paper/fig_null_control.png")
    args = ap.parse_args()

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "multignb_null_control.csv"
    ensure_iperf_server()

    all_rows: list[dict] = []
    if args.append and csv_path.exists():
        with open(csv_path) as fh:
            for r in csv.DictReader(fh):
                all_rows.append({
                    k: (None if v in ("", "None") else
                        (int(v) if k in ("pos", "pci", "ho_ok", "rep", "dl_mcs",
                                         "dur_s", "settle_s") else
                         float(v) if k in ("goodput_mbps", "mac_goodput_mbps") else v))
                    for k, v in r.items()})

    for arm in args.arms.split(","):
        if arm not in ARMS:
            print(f"unknown arm {arm}; known: {list(ARMS)}", flush=True)
            return 1
        for rep in range(args.reps or DEFAULT_REPS[arm]):
            print(f"[null] {arm} rep {rep} ...", flush=True)
            try:
                rows = run_rep(arm, rep, args.n)
            except Exception as e:      # a failed bring-up must not be silently averaged away
                print(f"  ERROR: {e}", flush=True)
                continue
            all_rows += rows
            print(f"  seq (pos,pci,Mbps,mcs): "
                  f"{[(r['pos'], r['pci'], None if r['goodput_mbps'] is None else round(r['goodput_mbps'], 2), r['dl_mcs']) for r in rows]}",
                  flush=True)

    if not all_rows:
        print("no data", flush=True)
        return 1

    fields = ["arm", "variant", "dur_s", "settle_s", "rep", "pos", "pci", "ho_ok",
              "goodput_mbps", "dl_mcs", "mac_goodput_mbps"]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    summary = summarize(all_rows)
    (out / "multignb_null_control.json").write_text(json.dumps(summary, indent=2, allow_nan=False))
    _make_figure(ROOT / args.fig, all_rows, summary)
    print("\n=== NULL CONTROL ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


def _make_figure(fig_path: Path, rows: list[dict], summary: dict) -> None:
    """Goodput vs sequence position on two identical cells, per instrument.

    A flat line is what "the cells are identical" should look like. The original
    instrument does not produce one.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    arms = [a for a in ("cochannel_tcp6", "cochannel_plateau") if a in summary["arms"]]
    if not arms:
        return
    labels = {"cochannel_tcp6": "original probe (6\\,s TCP, 3\\,s after HO)",
              "cochannel_plateau": "probe at TCP plateau (20\\,s settle)"}
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.6))

    for arm, colour in zip(arms, ("tab:red", "tab:blue")):
        for pci, mark in ((0, "o"), (1, "s")):
            pts = [(r["pos"], r["goodput_mbps"]) for r in rows
                   if r["arm"] == arm and r["pci"] == pci and r["goodput_mbps"] is not None]
            if pts:
                ax[0].scatter(*zip(*pts), marker=mark, alpha=0.75,
                              color=colour, s=32,
                              label=f"{labels[arm].split(' (')[0]}, PCI {pci}")
    ax[0].set_xlabel("measurement position in the handover sequence")
    ax[0].set_ylabel("DL goodput [Mbps]")
    ax[0].set_title("Two identical cells:\ngoodput should not depend on position")
    ax[0].grid(True, alpha=0.3)
    ax[0].legend(fontsize=6.5, loc="center right")

    xs = np.arange(len(arms))
    for i, est in enumerate(("naive_apparent_gain_pct", "balanced_apparent_gain_pct")):
        vals = [summary["arms"][a][est]["mean"] if summary["arms"][a][est] else 0.0 for a in arms]
        errs = [summary["arms"][a][est]["std"] if summary["arms"][a][est] else 0.0 for a in arms]
        ax[1].bar(xs + (i - 0.5) * 0.35, vals, 0.33, yerr=errs, capsize=3,
                  label=("naive (original estimator)" if i == 0 else "balanced (reversal design)"))
    ax[1].axhline(0, color="k", lw=1.2)
    ax[1].set_xticks(xs)
    ax[1].set_xticklabels(["original\nprobe", "plateau\nprobe"], fontsize=8)
    ax[1].set_ylabel("apparent cell effect [%]")
    ax[1].set_title("Truth is $0\\%$")
    ax[1].grid(True, axis="y", alpha=0.3)
    ax[1].legend(fontsize=7)

    fig.tight_layout()
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=130)
    plt.close(fig)
    print(f"wrote {fig_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
