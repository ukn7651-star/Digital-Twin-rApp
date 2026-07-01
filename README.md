# Digital-Twin-rApp — Sionna RT + OpenAirInterface

A cellular digital twin that pairs **Sionna RT** (site-specific ray-traced channel)
with **OpenAirInterface (OAI)** (a real 5G-NR protocol stack) to produce realistic
downlink throughput/KPIs. **No link-level model (no Sionna SYS).**

```
Sionna RT (dtrapp):  OSM bbox -> 3D scene -> ray-traced channel (CFR)  ─┐
                                                                        ▼
OpenAirInterface (oai):  real gNB + UE stack over that channel  ->  real KPIs (MCS, BLER, SINR, throughput)
```

## Two halves

- **`dtrapp/`** — the Sionna RT channel generator: OSM → 3D Mitsuba scene → seeded
  cells/UEs → ray-traced channel (CFR), exported to `output/channel/`.
  ```bash
  python3 -m dtrapp.runner.cli configs/example.yaml   # -> output/channel/cfr.npy, network.json
  ```
- **`oai/`** — build/run the OAI stack and bridge the RT channel into it. See
  **[`oai/README.md`](oai/README.md)**:
  ```bash
  bash oai/setup_oai.sh                 # build OAI (gNB + UE)
  bash oai/run_phytest.sh 30            # run a link, capture logs
  python3 oai/collect_kpis.py oai_run/gnb.log oai_run/kpis.csv
  python3 oai/cfr_to_oai_channel.py output/channel   # RT CFR -> OAI channel taps (bridge)
  ```

## Status

- Sionna RT channel generation: working (needs `sionna` + `sionna-rt`).
- OAI build + gNB/UE link + KPI extraction: working (verified in a CPU sandbox).
- RT → OAI channel injection: taps are produced; wiring them into the live
  rfsimulator (OWDT / `NVlabs/sionna-rk`) is the remaining integration step.
