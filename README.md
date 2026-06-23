# Digital Twin rApp — Throughput Engine (minimalist)

A standalone, **offline** engine that builds a virtual replica of a real-world
cellular environment and computes **downlink throughput** per user (UE) and per
cell, using **NVIDIA Sionna RT** ray tracing for radio propagation.

```
lat/lon bbox ─▶ OpenStreetMap 3D scene ─▶ Sionna RT ray tracing ─▶ SINR ─▶ throughput (Mbps)
                      (stage 1)                  (stage 3)        (stage 4)   (stage 5)
                base stations + users ─────────────▲
                      (stage 2)
```

This is a deliberately small reconstruction of the engine's behavior: one
pipeline, one config file, one command. No alternative engines, no extra flags.

## Pipeline (one module per stage)

| Stage | Module | What it does |
|-------|--------|--------------|
| 1. Geometry | `dtrapp/geometry/` | bbox → Overpass API → footprints → extrude to 3D → `scene.xml`. **No fallback**: errors out if OSM fails. |
| 2. Network | `dtrapp/network/` | Seeded random cells + UEs behind a **swappable** `NetworkDataSource`. |
| 3. Propagation | `dtrapp/propagation/` | Sionna RT: place TX/RX, ray-trace → per-link path gain (dB). |
| 4–5. KPI | `dtrapp/kpi/` | Multi-cell **SINR** → **Shannon throughput** with per-cell resource sharing. |
| 6. Runner | `dtrapp/runner/` | Snapshot loop, CSV/JSON output, CLI. |

## Install

```bash
pip install -r requirements.txt   # core
pip install sionna-rt              # the ray-tracing engine (CPU works; GPU optional)
```

## Run

```bash
# as a module (no install needed, run from the repo root):
python3 -m dtrapp.runner.cli configs/example.yaml

# or install the package and use the command:
pip install -e .
dtrapp configs/example.yaml
```

Outputs land in the configured `output_dir`:

- `ue_throughput.csv` — per-UE: serving cell, SINR (dB), throughput (Mbps).
- `cell_throughput.csv` — per-cell: attached UEs, aggregate throughput (Mbps).
- `throughput.json` — the full dataset across all snapshots.
- `scene/scene.xml` + `scene/meshes/*.ply` — the generated 3D world.

## Two seams kept for the future (per the brief)

- **Swappable data layer.** Real network data will replace the random generator.
  Implement `dtrapp.network.base.NetworkDataSource` and pass it to
  `run_simulation(config, network_source=...)` — nothing else changes.
- **Throughput model seam.** v1 uses `bandwidth · log2(1 + SINR)` with equal
  per-cell sharing. `dtrapp/kpi/throughput.py` is the single place to upgrade to
  5G-NR MCS tables, MIMO layers, and a PRB scheduler (the Rimedo-Labs-style model).

## Tests

```bash
python3 -m pytest -q
```

The pure-Python stages run without Sionna. `test_integration_sionna.py`
ray-traces a tiny scene and is skipped automatically when Sionna RT is absent.
