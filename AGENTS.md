# AGENTS.md

## Cursor Cloud specific instructions

Digital Twin rApp — an **offline, CLI** Python engine (no web/GUI service). It
builds a 3D scene from OpenStreetMap, ray-traces the channel with **Sionna RT**,
and computes 5G-NR downlink throughput with the **Sionna SYS** link-level chain.
Standard install/run/test commands live in `README.md`; notes below are only the
non-obvious cloud caveats.

### Environment
- Python deps live in a project virtualenv at `.venv` (created by the startup
  update script). Activate with `. .venv/bin/activate`, or call binaries
  directly (`.venv/bin/python`, `.venv/bin/pytest`).
- The heavy deps (`sionna-rt`, `sionna`, and the `torch`/CUDA wheels it pulls)
  are installed by the update script. They run **CPU-only** here
  (`torch.cuda.is_available()` is `False`); this is expected and the full
  pipeline still works.
- Ubuntu needs the `python3.12-venv` apt package for `python3 -m venv` to work;
  it is already present in the VM snapshot (do not add it to the update script).

### Running / testing
- Full pipeline (the end-to-end "hello world"):
  `python3 -m dtrapp.runner.cli configs/example.yaml` → writes CSV/JSON and the
  generated scene under `output/`.
- Tests: `python -m pytest -q`. Sionna RT/SYS tests build a scene from **canned
  OSM** (no network) and are auto-skipped when Sionna is not installed, so the
  suite runs anywhere.
- **No linter is configured** for this repo (no ruff/flake8/pylint/black); there
  is no lint step to run.

### Gotchas
- The geometry stage has **no fallback**: it fetches live building footprints
  from the OSM Overpass API (`https://overpass-api.de`) and raises `OverpassError`
  if the network call fails or returns no buildings. The full CLI run therefore
  needs outbound internet; the pytest suite does not.
- The application code lives on the `cursor/minimalist-sys-throughput-engine-00a7`
  branch. The `main` branch contains only a README.
