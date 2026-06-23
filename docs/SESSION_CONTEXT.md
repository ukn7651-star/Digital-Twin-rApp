# Session context (handoff for cloud / local agents)

This file is a context handoff so that **Cursor cloud agents (mobile/web) and the
local IDE agent share state** when working on this branch. The actual chat
history does not sync through git, so the relevant decisions, setup, and
verification results are recorded here. Update it as work progresses.

Branch: `cursor/digital-twin-rapp-throughput-engine-cb2d`

---

## 1. What this project is

Offline, ray-traced **downlink throughput engine** (Digital Twin rApp v1). Pipeline:
`lat/lon bbox -> OSM 3D scene -> Sionna RT -> SINR -> throughput (Mbps)`.
See `README.md` for the full stage map. Package root: `dtrapp/`, CLI entry point
`dtrapp` (`dtrapp/runner/cli.py`).

---

## 2. Environment

A local **mamba env named `dtrapp`** (Python 3.11) has all dependencies:

| Package | Version | Source |
|---|---|---|
| python | 3.11 | conda-forge |
| numpy / pyyaml / requests / shapely / pyproj / matplotlib | latest | conda-forge |
| pytest | 9.x | conda-forge |
| sionna-rt | 2.0.1 | pip |
| mitsuba | 3.8.0 | pip (dep of sionna-rt) |
| drjit | 1.3.1 | pip (dep of sionna-rt) |
| dtrapp | 0.1.0 | `pip install -e .` (editable) |

Recreate it:

```bash
mamba create -n dtrapp -c conda-forge -y python=3.11 \
  "numpy>=1.24" "pyyaml>=6.0" "requests>=2.31" "shapely>=2.0" \
  "pyproj>=3.6" "matplotlib>=3.7" "pytest>=7.4"
mamba run -n dtrapp pip install sionna-rt
mamba run -n dtrapp pip install -e .
```

Note: `pyproj` and `shapely` are declared in `requirements.txt`/`pyproject.toml`
but are **not imported anywhere in the source** (potential cleanup item).

Cloud agents run in their own VM, so they should create the env themselves (or
rely on `pip install -e .[rt,dev]` from `pyproject.toml`).

---

## 3. Verification status (all green)

- **Unit tests:** `python -m pytest -q` -> **34 passed** in the `dtrapp` env.
  Outside the env (no Sionna) it is 33 passed + 1 skipped (the Sionna
  integration test auto-skips via `pytest.importorskip`).
- **Manual hand-check:** `python verify.py` -> **42/42 checks passed**. This
  script takes a tiny controlled input and prints EXPECTED (with the source
  formula) vs ACTUAL for every stage (projection, extrusion, scene, network,
  analytical path gain, SINR, throughput, output, physics sanity). It uses no
  network and no Sionna, so it is fully deterministic and re-runnable.
- **Real run sanity (live Berlin bbox, Sionna RT):** built a 2,623-building
  scene and produced a throughput dataset; output rows satisfy
  `SE = log2(1+SINR)` (cap 7) and `throughput = (bandwidth / #attached) * SE`,
  and per-cell totals equal the sum of their UEs (conservation).

---

## 4. Key technical findings / decisions

- **Earth curvature is intentionally NOT modeled, and that is correct here.**
  `dtrapp/geometry/projection.py` uses a flat local ENU (equirectangular)
  frame. Sionna RT itself is flat-Earth local Cartesian (NVIDIA tiles large
  areas via `sionna-large-radio-maps`). At this scale (a few hundred m to ~2 km)
  the curvature drop is centimeters, far below ray-tracing fidelity. The only
  real gap: `BoundingBox` does not bound the box *size*, so a huge bbox would
  silently violate the flat-scene assumption. Suggested (not yet done) fix:
  warn/reject when the bbox diagonal exceeds a few km.
- **Engine comparison:** `--engine sionna` (real ray tracing) and
  `--engine analytical` (log-distance, test-only) give different absolute Mbps
  (e.g. ~18 vs ~12 mean on the example bbox); both preserve the
  closer/clearer-UE-gets-more-throughput trend. Analytical must be selected
  explicitly; it is never a silent fallback.

---

## 5. How to run

```bash
mamba activate dtrapp

# real ray-traced run (needs internet for the OSM Overpass fetch)
dtrapp --bbox 52.5132 13.375 52.5168 13.381 --engine sionna --snapshots 1 --output output_sionna

# pipeline development without ray tracing
dtrapp --config configs/example.yaml --engine analytical --output output_analytical
```

Outputs: `ue_throughput.csv`, `cell_throughput.csv`, `throughput.json`,
optional `heatmap_snapshot0.png`, plus `scene/scene.xml` + `meshes/*.ply`.
Use a distinct `--output` per run so engines don't overwrite each other.

---

## 6. Repo hygiene notes

- `verify.py` IS committed (so cloud agents can re-verify).
- `sync.sh` is a **local-only** helper (kept out of git via `.git/info/exclude`)
  that auto-syncs the local working copy with this branch on the developer's
  machine; it is machine-specific and intentionally not committed.
- `output*/` is git-ignored.

---

## 7. Open follow-ups (none blocking)

- Optional: add a bounding-box size guard (see section 4).
- Optional: remove unused `pyproj`/`shapely` deps, or start using them.
- Out of scope for v1: calibrating absolute Mbps against real measured KPIs;
  live-data ingestion; ML surrogate; uplink.
