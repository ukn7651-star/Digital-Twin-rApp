# Digital-Twin rApp — site-specific multi-cell 5G throughput twin

An open, CPU-only **network digital twin** that estimates per-UE and per-cell
**downlink throughput** for a multi-cell, multi-user 5G network on a
**site-specific, ray-traced** channel, and closes an **O-RAN traffic-steering
control loop** on top of it.

- **Geometry** is built from OpenStreetMap buildings.
- **Propagation** is ray-traced with NVIDIA Sionna RT.
- **Throughput** comes from a link model **measured on OpenAirInterface's (OAI)
  real physical layer** (`nr_dlsim`), driven by per-resource-element SINR with
  EESM link abstraction — not a closed-form formula.
- A **traffic-steering rApp** rebalances load across cells via cell-individual
  offsets (CIO).
- The exact ray-traced channel can be **injected into a live OAI gNB–UE link**,
  grounding the per-link realism in a real 5G stack.

```
OSM bbox ─▶ 3D scene ─▶ Sionna RT channel ─┬─▶ multi-cell KPI engine ─▶ per-UE/cell throughput
                                           │        (per-RE SINR + EESM +
                                           │         OAI-measured MCS curve)
                                           ├─▶ traffic-steering rApp (CIO load balancing)
                                           └─▶ OAI in the loop (exact channel injection)
```

## Repository layout

| Path | Contents |
|---|---|
| `dtrapp/` | The twin: geometry, propagation, KPI engine, rApp, runners |
| `dtrapp/kpi/` | Per-RE SINR + EESM engine and the OAI-measured link curve |
| `dtrapp/rapp/` | Traffic-steering (CIO) load-balancing rApp |
| `dtrapp/oai_bridge.py` | Twin→OAI interference-floor bridge |
| `dtrapp/runner/` | CLIs: full pipeline, rApp, and the experiment sweep |
| `oai/` | OAI-side scripts + docs (build, run, channel injection, full stack) |
| `experiments/results/` | Aggregated results (CSV/JSON) and figures |
| `paper/` | IEEE conference paper (LaTeX + figures + PDF) |
| `tests/` | Unit tests |
| `configs/example.yaml` | Example scenario configuration |

## Installation

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install sionna-rt sionna     # ray tracer + link-level utilities (a few GB)
```

The ray tracer runs on CPU or GPU. If a GPU driver is incompatible, force CPU by
prefixing commands with `CUDA_VISIBLE_DEVICES=""`.

## Quickstart

**1. Run the full twin** (OSM → ray tracing → per-UE/per-cell throughput):
```bash
python3 -m dtrapp.runner.cli configs/example.yaml
# writes output/ue_throughput.csv, cell_throughput.csv, throughput.json,
# and output/channel/{cfr.npy, network.json}
```

**2. Run the traffic-steering rApp** on the exported channel:
```bash
python3 -m dtrapp.runner.rapp_cli output/channel
# prints baseline vs. rApp gains and writes CDF / convergence plots
```

**3. Reproduce the experiment matrix** (multiple cities × random layouts + load sweep):
```bash
python3 -m dtrapp.runner.sweep --seeds 8 --out experiments/results
```
See [`experiments/README.md`](experiments/README.md).

## OpenAirInterface integration

The twin exports the ray-traced channel so a real OAI stack can run over it. See
[`oai/README.md`](oai/README.md) for building OAI, running a gNB–UE link, and
injecting the exact channel, and [`oai/README_full_stack.md`](oai/README_full_stack.md)
for the multi-UE Standalone + FlexRIC + iperf3 path.

## Results (summary)

Across three urban scenes (Berlin, Paris, Manhattan) and eight random layouts each
(24 runs), the traffic-steering rApp versus strongest-cell association:

| Metric | Overall (mean ± std) |
|---|---|
| Median per-UE throughput gain | +9.5 ± 11.3% |
| Served cell-edge throughput gain | +22.4 ± 24.8% |
| Jain fairness gain | +9.1 ± 11.0% |
| Peak cell load change | −0.75 UEs |
| Aggregate rate / UE outage | ≈ unchanged |

Per-UE throughput rises 1.5–1.7× as inter-cell load falls to idle. Full numbers in
`experiments/results/summary.json`.

## Paper

An IEEE conference write-up is in [`paper/`](paper/) (LaTeX + figures + compiled
PDF); see [`paper/README.md`](paper/README.md) to build it.

## Tests

```bash
pip install pytest
python -m pytest -q
```
The unit tests (geometry, network, KPI engine, rApp, bridges) run without the ray
tracer; the single Sionna RT integration test additionally needs `sionna-rt`.

## License

Apache-2.0 (see `pyproject.toml`).
