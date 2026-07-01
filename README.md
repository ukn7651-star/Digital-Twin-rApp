# Digital Twin rApp — Throughput Engine (minimalist, RT + SYS)

A standalone, **offline** engine that builds a virtual replica of a real-world
cellular environment and computes **downlink throughput** per user (UE) and per
cell, using **NVIDIA Sionna RT** ray tracing for the channel and the **full
NVIDIA Sionna SYS link-level chain** (post-equalization SINR → link adaptation →
proportional-fair scheduling) for throughput. One static scene in, one throughput
result out — no time stepping.

```
lat/lon bbox ─▶ OSM 3D scene ─▶ Sionna RT channel (CFR) ─▶ Sionna SYS link level ─▶ throughput (Mbps)
                  (stage 1)          (stage 3)            (post-eq SINR + LA + PF)
            base stations + users ───────▲                      (stages 4-5)
                  (stage 2)
```

This is a deliberately small reconstruction of the engine's behavior: one
pipeline, one config file, one command. No alternative engines, no extra flags.
It is the **RT + Sionna SYS** counterpart of the RT + Shannon baseline: the
throughput stage is the full Sionna SYS system-level chain.

## Pipeline (one module per stage)

| Stage | Module | What it does |
|-------|--------|--------------|
| 1. Geometry | `dtrapp/geometry/` | bbox → Overpass API → footprints → extrude to 3D → `scene.xml`. **No fallback**: errors out if OSM fails. |
| 2. Network | `dtrapp/network/` | Seeded random cells + UEs behind a **swappable** `NetworkDataSource`. |
| 3. Propagation | `dtrapp/propagation/` | Sionna RT: place TX/RX (antenna arrays from config), ray-trace → channel frequency response (CFR). |
| 4–5. KPI | `dtrapp/kpi/` | **Full Sionna SYS link-level chain**: post-eq SINR (RZF + LMMSE) with inter-cell interference → link adaptation (5G-NR MCS/BLER) → PF resource sharing. |
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
- **Throughput model seam.** Stages 4-5 are the full Sionna SYS link-level chain
  in `dtrapp/kpi/sys_link.py` (the single place the throughput model lives; the
  propagation and runner layers are untouched).

## Throughput model (RT + SYS link level)

`dtrapp/kpi/sys_link.py` turns the ray-traced channel into throughput exactly the
way Sionna SYS does for system-level 5G-NR studies:

1. **Channel.** `SionnaPropagationEngine.compute_cfr` ray-traces the channel
   frequency response per cell → UE over a representative OFDM resource grid.
2. **Association.** Each UE attaches to the cell with the strongest received
   power.
3. **Post-equalization SINR.** Per UE, `RZFPrecodedChannel` (regularized
   zero-forcing precoding — beamforming gain from the 4-element BS array) +
   `LMMSEPostEqualizationSINR` produce the post-equalization SINR. Inter-cell
   interference (full-buffer neighbours) is folded into the effective noise.
4. **Link adaptation.** `InnerLoopLinkAdaptation` + `PHYAbstraction` pick the
   highest 5G-NR MCS within `bler_target`; the MCS gives a capped spectral
   efficiency `SE = Qm · coderate`.
5. **Scheduling.** Proportional-fair sharing of each cell's airtime among its
   UEs — on a static full-buffer snapshot this is provably equal airtime
   (`1/K_cell`). Per-UE goodput `= (B_cell / K_cell) · SE · (1 − bler_target)`.

Config knobs: `bler_target` (default `0.1`), `mcs_table_index` (`1` = up to
64QAM, `2` = up to 256QAM), `subcarrier_spacing_hz`, `num_subcarriers`,
`num_ofdm_symbols`.

## Antennas (config-driven)

The antenna arrays are set in the config, not hardcoded:
`bs_antenna_rows`/`bs_antenna_cols`/`bs_antenna_pattern`/`bs_antenna_polarization`
for the base stations, the `ue_antenna_*` equivalents for the UEs, plus
`antenna_spacing` (in wavelengths) and `downtilt_deg`.

Note (per-device antennas): Sionna RT applies **one** TX array to all
transmitters and **one** RX array to all receivers per solve, so the current
build uses a single BS array and a single UE array. Heterogeneous antennas
(different arrays per BS/UE, as real data may have) would be handled by grouping
devices by antenna type and solving per group — a planned extension carried
through the swappable data layer.

## Tests

```bash
python3 -m pytest -q
```

The pure-Python stages (geometry, network) run without Sionna. The Sionna RT
integration test and the link-level KPI tests build a tiny scene from canned OSM
and are skipped automatically when Sionna is not installed.

## Limitations (read this)

This engine keeps the full multi-cell, multi-UE network, but makes deliberate
simplifications:

1. **The throughput stage is a model.** Sionna SYS maps SINR → MCS → rate with a
   PHY *abstraction* (`PHYAbstraction` + link-adaptation), not a running protocol
   stack. It's realistic and standards-based, but it is not real LDPC/HARQ/scheduler
   behaviour. (The sibling RT+OAI branch replaces this stage with real OAI data.)
2. **Static snapshot — no mobility.** One instant; no UE movement, Doppler, or fast
   fading. Consequently **scheduling reduces to equal airtime**: on a static
   full-buffer snapshot a proportional-fair scheduler is provably equal-airtime, so
   there is a single scheduling model and no meaningful "real scheduler" alternative
   without adding mobility.
3. **Inter-cell interference is modelled as noise.** Each UE's SINR folds the other
   cells' power into the effective noise (the standard interference-as-noise model);
   cells' waveforms are not physically combined.
4. **Beamforming** is the RZF precoding array gain, not a full MIMO multi-layer chain.
5. **Random network data.** Cells/UEs/traffic are seeded-random stand-ins until real
   network data is integrated (the data layer is swappable by design).
