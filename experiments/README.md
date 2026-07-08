# Experiments

Reproducible experiment matrix for the twin, the traffic-steering rApp, and the two
fidelity gaps (model-vs-model, and twin-vs-live-stack).

## 1. rApp sweep (analytical twin only, no OAI)

```bash
CUDA_VISIBLE_DEVICES="" python3 -m dtrapp.runner.sweep --seeds 8 --out experiments/results
```

For each scene (Berlin, Paris, Manhattan) the harness fetches the OpenStreetMap
geometry once and reuses it across seeds; only the random network placement and the
ray tracing re-run per seed. It also sweeps the inter-cell load factor on a cached
channel. About five minutes on a commodity CPU.

Outputs: `summary.json`, `sweep_runs.csv`, `load_sweep.csv`, `fig_cdf_pooled.png`,
`fig_outage_vs_load.png`, `fig_throughput_vs_load.png`.

## 2. Model-vs-model: what a twin says, and what acting on it costs (no OAI)

```bash
CUDA_VISIBLE_DEVICES="" python3 experiments/decision_regret.py --seeds 8   # the headline
CUDA_VISIBLE_DEVICES="" python3 experiments/fidelity_gap.py                # OAI vs Shannon only
python3 experiments/fidelity_gap.py --from-csv                             # summary only
```

`decision_regret.py` runs the identical rApp on twins that differ **only** in the
SINR->throughput curve, and separates two errors:

* **reporting** error — how far the surrogate's own predicted throughput sits from
  the OAI-grounded twin's;
* **decision** error (*regret*) — the proportional-fair utility lost by planning on the
  surrogate and being evaluated on the OAI-grounded twin.

The surrogates are the Shannon-optimal staircase and two one-parameter analytical
curves fitted to the OAI data (a SINR offset `delta`, and an attenuation `alpha`) — the
honest baselines. Result: a single fitted `delta = 4.71 dB` cuts reporting error from
41.3% to 1.5% and regret from 0.76 to 0.04 nats, while the customary "decisions differ"
statistic (33–42% for *every* surrogate) separates none of them.

Outputs `decision_regret.{csv,json}`, `paper/fig_decision_regret.png`.

## 3. Live-stack experiments (need a full OAI SA host)

Check the host first: `bash oai/check_host.sh` must print `READY`.
The 5G core must be up and `iperf3 -s` running on `oai-ext-dn`.

### 3a. Single gNB: the link-abstraction gap

```bash
python3 experiments/real_fidelity_gap.py                 # sweeps dl_max_mcs on a live gNB
python3 experiments/real_fidelity_gap.py --skip-measure  # re-analyse the committed CSV
```

Pins the DL operating point by capping the scheduler MCS, sweeps the cap, and measures
delivered goodput. The twin's link rate is evaluated at the *cell's* occupied bandwidth,
read from the gNB conf (106 PRB @ 30 kHz = 38.16 MHz).

Two references are reported, and conflating them is what makes "fidelity gap" numbers
irreproducible:

* **twin -> OAI's MAC** — real 5G-NR scheduler code paying TDD duty, DMRS, PDCCH, HARQ.
  This ratio is *constant*: `kappa = 0.470 +/- 0.004` (CV 0.8% over MCS 0–28). Because it
  is constant it cancels in ratios, so the twin's *relative* per-UE steering-gain
  prediction matches the real MAC to `+1.2 +/- 5.7` points.
* **twin -> application goodput** — a further 80% down, *growing* with SINR (72% -> 87%).
  That growth is the rfsimulator's compute ceiling, not the twin's abstraction error.

Both curves are indexed by the twin's *operating MCS*, not interpolated along SINR: the
twin's rate is a staircase in SINR, so interpolating a measured curve along SINR would
compare a staircase with a ramp and manufacture a gap between the knots.

Outputs `real_goodput_calib.csv`, `real_fidelity_gap.{csv,json}`, `paper/fig_real_fidelity_gap.png`.

### 3b. Null control: what does the multi-cell harness measure when nothing is there?

```bash
python3 experiments/multignb_null_control.py
```

Runs the 2-cell harness with **both cells carrying the same clean channel**, so the
true cell effect is exactly zero. Anything it reports is instrument bias. Arms cross the
probe (the original 6 s TCP flow started 3 s after each handover vs TCP measured at its
plateau) with the cells (stock `pci1` DU, on a different carrier, vs a co-channel DU1
identical to DU0 except PCI).

Result: the original probe reports `-21.0 +/- 1.4%` (mean DL MCS 16.5 on PCI 0 vs 10.7 on
PCI 1); probing at TCP's plateau gives `-2.4 +/- 2.9%`, consistent with zero, MCS 28 on
both cells. Outputs `multignb_null_control.{csv,json}`, `paper/fig_null_control.png`.

This exists because the first multi-cell result was an instrument reading itself: the old
protocol measured once before the handover (always DU0) and once after it (always DU1) and
relabelled those numbers by cell, so measurement order and cell identity were perfectly
confounded — and since `ci trigger_f1_ho` always moves DU0->DU1, the reported *sign* was a
pure function of the direction the rApp happened to choose.

**A saturating UDP probe, the textbook fix, is also invalid here**: in reverse mode iperf3
reports the *sending* rate, so through a 9.8 Mbps MAC an 8 Mbps offer reads exactly
8.00 Mbps at ~0% loss.

### 3c. rfsim noise-floor calibration

```bash
python3 experiments/rfsim_noise_calib.py
```

RT injection reproduces the *relative* per-cell link gain, not the absolute SINR
(rfsim's noise floor is a config knob, not kTB·NF). This measures `noise_power_dB ->
operating DL MCS` with one cell muted.

Result: **not invertible.** Sweeping the floor from -22 to -2 dB gives operating MCS
`8, 19, 14, 18, 14, 0` — non-monotone. The reference cell therefore cannot be placed at a
target operating point, so absolute SINR matching is impossible on this emulator.
Outputs `rfsim_noise_calib.{csv,json}`.

### 3d. Controlled multi-cell fidelity gap — **a documented negative result**

```bash
python3 experiments/multignb_fidelity_gap.py
python3 experiments/multignb_fidelity_gap.py --skip-measure
```

Two co-channel cells (CU + two F1 DUs); each UE->cell ray-traced channel is injected on
the UE (the rfsim *server*, so DU-k's samples pass through `rfsimu_channel_ue{k}`), and
`rxAddInput` sums both DUs' waveforms, making the non-serving cell real co-channel
interference rather than a noise-floor proxy. The rApp's decision executes as a real F1
handover, measured with a reversal (A/B/A/B) design.

**The injection works and is verified** — every layout's UE log shows
`[RT] injected 1 taps into rfsimu_channel_ue0/ue1` carrying the twin's link gains exactly,
and the UE reaches MCS 27 on the twin's stronger cell. **The measurement does not close:**

1. With channel models on both rfsim connections the loop destabilises — over three
   layouts, two F1 handovers never complete and the third only through 70 UE
   re-synchronisations, so its goodput measures the emulator's recovery, not the channel.
2. Absolute SINR cannot be matched (see 3c), and at the idle-neighbour condition a one-UE
   stack presents, the twin puts both cells at MCS 28 and predicts *no* link-level
   difference in two of three layouts.

The driver records the `outcome` per layout rather than dropping it, so the negative
result is reproducible. Outputs `multignb_fidelity_gap.{csv,json}`, `multignb_seq_*.json`.

## Notes

- `served cell-edge` is the 5th percentile among UEs with non-zero throughput
  (robust to coverage holes); `outage` is the fraction of UEs with zero throughput.
- rApp gains are reported as mean ± standard deviation over seeds and pooled across
  all runs; a gain is undefined for a run whose baseline metric is zero.
- Every number in the paper is reproducible from `experiments/results/*` or the OAI
  logs in `oai_run/`.
