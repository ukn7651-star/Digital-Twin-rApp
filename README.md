# Digital Twin rApp — Throughput Engine (v1)

A standalone, **offline** simulation engine that builds a high-fidelity virtual
replica of a real-world cellular environment and computes **downlink throughput**
per user (UE) and per cell, using **NVIDIA Sionna RT ray tracing** for radio
propagation.

It re-creates the *backend* of the Rimedo Labs Digital Twin rApp: turn a
scenario (a place + base stations + users) into a throughput dataset.

```
lat/lon bbox ──▶ OpenStreetMap 3D scene ──▶ Sionna RT ray tracing ──▶ SINR ──▶ throughput (Mbps)
                          (stage 1)            (stage 3)        (stage 4)   (stage 5)
                    base stations + users  ──────────────▲
                          (stage 2)
```

---

## How it's built — small goals that combine into the engine

The codebase follows the recommended build order. Each stage is a self-contained
module with its own tests, and they compose into the full pipeline in
`dtrapp/runner/pipeline.py`.

| Goal | Module | What it does | Status |
|------|--------|--------------|--------|
| **0. Scaffold** | `dtrapp/config.py` | Typed config (bbox, network, propagation, KPI, runner) with YAML load/save. | ✅ |
| **1. Geometry** | `dtrapp/geometry/` | bbox → Overpass API → building footprints → extrude to 3D → write Mitsuba `scene.xml`. **No fallback**: errors out if OSM fails. | ✅ |
| **2. Network** | `dtrapp/network/` | Seeded random generator for cells + UEs behind a **swappable** `NetworkDataSource` interface. | ✅ |
| **3. Propagation** | `dtrapp/propagation/` | Sionna RT wrapper: place TX/RX, run `PathSolver` → per-link path gain (dB). | ✅ |
| **4–5. KPI** | `dtrapp/kpi/` | Multi-cell **SINR** (with inter-cell interference) → **Shannon throughput** with per-cell resource sharing. | ✅ |
| **6. Runner** | `dtrapp/runner/` | Snapshot loop, CSV/JSON/heatmap output, CLI entry point. | ✅ |
| **7. Sanity** | `tests/` | Closer/clearer UE ⇒ higher throughput; resource sharing; reproducibility. | ✅ |

---

## Install

```bash
pip install -r requirements.txt        # core (geometry, network, KPI, runner)
pip install sionna-rt                   # ray-tracing engine (CPU works; GPU optional)
# or, as a package:
pip install -e .[rt,dev]
```

Sionna RT runs **CPU-only** out of the box (Dr.Jit LLVM backend) and uses a CUDA
backend automatically when a GPU is present.

## Run

```bash
# Full ray-traced run from a YAML scenario:
dtrapp --config configs/example.yaml

# Quick run from a bounding box (south, west, north, east):
dtrapp --bbox 52.515 13.377 52.5165 13.3795 --snapshots 3 --seed 7

# Develop the pipeline without Sionna RT (test-only analytical propagation):
dtrapp --config configs/example.yaml --engine analytical
```

Outputs land in the configured `output_dir`:

- `ue_throughput.csv` — per-UE: serving cell, SINR (dB), spectral efficiency, throughput (Mbps).
- `cell_throughput.csv` — per-cell: attached UEs, aggregate throughput (Mbps).
- `throughput.json` — the full dataset across all snapshots.
- `scene/scene.xml` + `scene/meshes/*.ply` — the generated 3D world.
- `heatmap_snapshot0.png` — optional UE-throughput scatter (when `write_heatmap`).

---

## Design decisions (matching the v1 scope)

- **Ray tracing is the engine.** `SionnaPropagationEngine` runs every time. There
  is no ML surrogate.
- **No fallback geometry.** OSM is the single source of the world. If Overpass
  cannot be fetched/parsed, or returns no buildings, the engine raises
  `SceneBuildError` and stops — it never substitutes a different scene.
- **Swappable data layer.** Both the random generator and any future real-data
  source implement `dtrapp.network.base.NetworkDataSource`. Pass a real source to
  `run_simulation(..., network_source=...)` with no other changes.
- **Multi-cell SINR.** `serving signal / (other cells' interference + noise)`.
- **Throughput model seam.** v1 uses `bandwidth · log2(1 + SINR)` with equal
  per-cell resource sharing. `dtrapp/kpi/throughput.py` is the single place to
  swap in 5G-NR MCS tables, MIMO layers, and a PRB scheduler later.

## Coordinate frame

All stages share one local **ENU** metric frame (meters, +z up) centered on the
bbox center (`dtrapp/geometry/projection.py`), so buildings, cells, and UEs drop
straight into the Sionna scene.

## Tests

```bash
python -m pytest -q
```

The pure-Python stages (geometry math, network generation, SINR/throughput,
output) are fully unit-tested and run without Sionna. `test_integration_sionna.py`
ray-traces a tiny scene and is skipped automatically when Sionna RT is absent.

## Out of scope (v1)

Live-data interfaces (EIAP/O1/R1), rApp packaging, ML surrogates, uplink,
anomaly injection, and statistical traffic modeling. See the project brief.
