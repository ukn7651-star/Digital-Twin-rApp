# Digital-Twin-rApp — Sionna RT + OpenAirInterface

A cellular digital twin that computes per-UE / per-cell **downlink throughput** on a
site-specific, ray-traced channel. The SINR→throughput **mapping** comes from
**OpenAirInterface (OAI)** — a real 5G-NR protocol stack — instead of a link-level
formula. **No Sionna SYS.**

```
dtrapp:  OSM bbox -> 3D scene -> Sionna RT channel (CFR) -> multi-cell SINR
                                                              │
                                    OAI-measured SINR->MCS curve (nr_dlsim)
                                                              ▼
                              per-UE + per-cell throughput  (ue/cell_throughput.csv)
```

## Full engine (one command)

```bash
python3 -m dtrapp.runner.cli configs/example.yaml
# -> output/ue_throughput.csv, cell_throughput.csv, throughput.json
#    output/channel/cfr.npy, network.json   (for OAI-in-the-loop)
```

Stages: OSM → 3D scene → cells/UEs → Sionna RT channel → **association + multi-cell
SINR** → **OAI-measured SINR→MCS→rate mapping** → proportional-fair scheduling →
per-UE and per-cell throughput. The `notebooks/dtrapp_oai_walkthrough.ipynb` mirrors
the Sionna SYS notebook for a side-by-side comparison on the same scene.

## Where OAI comes in

OAI supplies the throughput mapping in two ways:

1. **Characterized curve (default, fast).** `oai/characterize_link.py` runs OAI's PHY
   simulator `nr_dlsim` across SNR × MCS and records the real link-adaptation curve
   into `oai/sinr_throughput_table.json`. The engine maps each UE's SINR through it.
2. **In the loop (exact channel).** The exported CFR can drive a live OAI gNB↔UE link
   over the *exact* ray-traced channel. See **[`oai/README.md`](oai/README.md)**:
   ```bash
   bash oai/setup_oai.sh                                   # build OAI (+ apply RT patch)
   python3 oai/cfr_to_oai_channel.py output/channel --base-conf <phytest.conf>
   OAI_RT_TAPS=output/channel/oai_rt_taps.txt \
   CONF=output/channel/gnb_rtchan.conf bash oai/run_phytest.sh 30
   python3 oai/collect_kpis.py oai_run/gnb.log oai_run/kpis.csv
   ```

## Status

- Full ray-traced throughput engine (per-UE/per-cell CSV/JSON): working.
- OAI-measured SINR→MCS curve via `nr_dlsim`: generated and committed.
- OAI build + gNB/UE link + KPI extraction: working (verified in a CPU sandbox).
- RT → OAI exact-channel injection: working (patch applied by `setup_oai.sh`);
  path loss is masked on the UL by power control (see `oai/README.md`).
