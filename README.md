# Digital Twin rApp — Throughput Engine (minimalist, RT + SYS)

A standalone, **offline** engine that builds a virtual replica of a real-world
cellular environment and computes **downlink throughput** per user (UE) and per
cell, using **NVIDIA Sionna RT** ray tracing for radio propagation and
**NVIDIA Sionna SYS** link adaptation for the SINR → throughput mapping. One
static scene in, one throughput result out — no time stepping.

```
lat/lon bbox ─▶ OpenStreetMap 3D scene ─▶ Sionna RT ray tracing ─▶ SINR ─▶ Sionna SYS link adaptation ─▶ throughput (Mbps)
                      (stage 1)                  (stage 3)        (stage 4)            (stage 5)
                base stations + users ─────────────▲
                      (stage 2)
```

This is a deliberately small reconstruction of the engine's behavior: one
pipeline, one config file, one command. No alternative engines, no extra flags.
It is the **RT + Sionna SYS** counterpart of the RT + Shannon baseline: only the
throughput stage differs.

## Pipeline (one module per stage)

| Stage | Module | What it does |
|-------|--------|--------------|
| 1. Geometry | `dtrapp/geometry/` | bbox → Overpass API → footprints → extrude to 3D → `scene.xml`. **No fallback**: errors out if OSM fails. |
| 2. Network | `dtrapp/network/` | Seeded random cells + UEs behind a **swappable** `NetworkDataSource`. |
| 3. Propagation | `dtrapp/propagation/` | Sionna RT: place TX/RX, ray-trace → per-link path gain (dB). |
| 4–5. KPI | `dtrapp/kpi/` | Multi-cell **SINR** → **Sionna SYS link adaptation** (5G-NR MCS / BLER) with per-cell resource sharing. |
| 6. Runner | `dtrapp/runner/` | Orchestration, CSV/JSON output, CLI. |

## Install

```bash
pip install -r requirements.txt   # core
pip install sionna-rt              # the ray-tracing engine (CPU works; GPU optional)
pip install sionna                 # Sionna SYS, for the link-adapted throughput model
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
- `throughput.json` — the full per-UE and per-cell dataset.
- `scene/scene.xml` + `scene/meshes/*.ply` — the generated 3D world.

## Two seams kept for the future (per the brief)

- **Swappable data layer.** Real network data will replace the random generator.
  Implement `dtrapp.network.base.NetworkDataSource` and pass it to
  `run_simulation(config, network_source=...)` — nothing else changes.
- **Throughput model seam.** This build maps SINR → throughput with **Sionna SYS
  link adaptation**: `InnerLoopLinkAdaptation` picks the highest 5G-NR MCS whose
  BLER stays within `bler_target` (via `PHYAbstraction`), and the chosen MCS gives
  a capped spectral efficiency. `dtrapp/kpi/throughput.py` is the single place
  this lives; the SINR and runner layers are untouched. Next steps toward the full
  Rimedo-Labs-style model: MIMO layers and a PF scheduler (Sionna SYS provides
  both, `PFSchedulerSUMIMO`).

## Throughput model (RT + SYS)

- `dtrapp/kpi/sinr.py` computes the multi-cell SINR from the ray-traced path gains
  (signal / (inter-cell interference + thermal noise)) — pure NumPy.
- `dtrapp/kpi/throughput.py` feeds each UE's effective SINR to Sionna SYS:
  - `InnerLoopLinkAdaptation` → MCS index for the target BLER,
  - spectral efficiency `SE = Qm · coderate` (capped by the modulation order),
  - per-UE goodput `(B_cell / K_cell) · SE · (1 − bler_target)`.
- Config knobs: `bler_target` (default `0.1`) and `mcs_table_index`
  (`1` = up to 64QAM, `2` = up to 256QAM).

## Tests

```bash
python3 -m pytest -q
```

The pure-Python stages (geometry, network, SINR) run without Sionna.
`test_integration_sionna.py` ray-traces a tiny scene and is skipped when Sionna RT
is absent; the end-to-end KPI test is skipped when **Sionna SYS** is absent.
