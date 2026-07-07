# Experiments

Reproducible experiment matrix for the twin and the traffic-steering rApp.

## Run

```bash
CUDA_VISIBLE_DEVICES="" python3 -m dtrapp.runner.sweep --seeds 8 --out experiments/results
```

For each scene (Berlin, Paris, Manhattan) the harness fetches the OpenStreetMap
geometry once and reuses it across seeds; only the random network placement and the
ray tracing re-run per seed. It also sweeps the inter-cell load factor on a cached
channel. About five minutes on a commodity CPU.

## Outputs (`results/`)

- `summary.json` — aggregate statistics (per-scene and overall means/std, outage).
- `sweep_runs.csv` — one row per (scene, seed): baseline vs. rApp metrics.
- `load_sweep.csv` — throughput and outage vs. inter-cell load factor.
- `fig_cdf_pooled.png` — per-UE throughput CDF, baseline vs. rApp.
- `fig_outage_vs_load.png` — UE outage vs. inter-cell load, per scene.
- `fig_throughput_vs_load.png` — mean throughput vs. inter-cell load, per scene.

## Notes

- `served cell-edge` is the 5th percentile among UEs with non-zero throughput
  (robust to coverage holes); `outage` is the fraction of UEs with zero throughput.
- rApp gains are reported as mean ± standard deviation over seeds and pooled across
  all runs; a gain is undefined for a run whose baseline metric is zero.
