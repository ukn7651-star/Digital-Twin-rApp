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

## 2. Model-vs-model fidelity gap (no OAI)

```bash
CUDA_VISIBLE_DEVICES="" python3 experiments/fidelity_gap.py
python3 experiments/fidelity_gap.py --from-csv     # recompute the summary only
```

Runs the identical rApp on two twins that differ **only** in the SINR->throughput
curve (OAI-measured vs Shannon-optimal thresholds). Outputs `fidelity_gap.{csv,json}`,
`fig_fidelity_gap.png`.

## 3. Live-stack experiments (need a full OAI SA host)

Check the host first: `bash oai/check_host.sh` must print `READY`.
The 5G core must be up and `iperf3 -s` running on `oai-ext-dn`.

### 3a. Single gNB: the link-abstraction gap

```bash
python3 experiments/real_fidelity_gap.py                 # sweeps dl_max_mcs on a live gNB
python3 experiments/real_fidelity_gap.py --skip-measure  # re-analyse the committed CSV
```

Pins the DL operating point by capping the scheduler MCS, sweeps the cap, and measures
delivered goodput with a **saturating UDP probe** (TCP plateaus near 10.5 Mbps on this
stack regardless of MCS and needs ~30 s of slow start). The twin's link rate is
evaluated at the *cell's* occupied bandwidth, read from the gNB conf (106 PRB @ 30 kHz
= 38.16 MHz), not at the twin scenario's 20 MHz. Outputs `real_goodput_calib.csv`,
`real_fidelity_gap.{csv,json}`, `paper/fig_real_fidelity_gap.png`.

### 3b. Null control: what does the multi-cell harness measure when nothing is there?

```bash
python3 experiments/multignb_null_control.py
```

Runs the 2-cell harness with **both cells carrying the same clean channel**, so the
true cell effect is exactly zero. Four arms cross the instrument (original 6 s TCP
started 3 s after the handover vs saturating UDP after a settle) with the cells
(stock `pci1` DU on a different carrier vs a co-channel DU1 identical to DU0 except
PCI). Outputs `multignb_null_control.{csv,json}`.

This exists because the first multi-cell result was an instrument reading itself: the
old protocol measured once before the handover (always DU0) and once after it (always
DU1) and relabelled those numbers by cell, so measurement order and cell identity were
perfectly confounded.

### 3c. rfsim noise-floor calibration

```bash
python3 experiments/rfsim_noise_calib.py
```

RT injection reproduces the *relative* per-cell link gain, not the absolute SINR
(rfsim's noise floor is a config knob). This measures `noise_power_dB -> operating DL
MCS` with one cell muted, so the multi-cell experiment can place the reference cell at
the twin's predicted operating point. Outputs `rfsim_noise_calib.{csv,json}`.

### 3d. Controlled multi-cell fidelity gap

```bash
python3 experiments/multignb_fidelity_gap.py            # needs 3c first
python3 experiments/multignb_fidelity_gap.py --skip-measure
```

Two co-channel cells (CU + two F1 DUs); each UE->cell ray-traced channel is injected on
the UE (the rfsim *server*, so DU-k's samples pass through `rfsimu_channel_ue{k}`), and
`rxAddInput` sums both DUs' waveforms, making the non-serving cell real co-channel
interference. The rApp's decision is executed as a real F1 handover, and goodput is
measured with a reversal (A/B/A/B) design. The run **aborts** if the per-cell injection
is not confirmed in the UE log.

The comparison is the **link component** of the steering gain: the twin's per-UE gain
also contains an airtime term `B_cell/K`, which a stack with one real UE cannot exhibit.
That term is reported separately (`twin_full_gain_pct`) and is *not* what the delivered
gain is compared against.

Outputs `multignb_fidelity_gap.{csv,json}`, `multignb_seq_*.json`, `paper/fig_multignb_gap.png`.

## Notes

- `served cell-edge` is the 5th percentile among UEs with non-zero throughput
  (robust to coverage holes); `outage` is the fraction of UEs with zero throughput.
- rApp gains are reported as mean ± standard deviation over seeds and pooled across
  all runs; a gain is undefined for a run whose baseline metric is zero.
- Every number in the paper is reproducible from `experiments/results/*` or the OAI
  logs in `oai_run/`.
