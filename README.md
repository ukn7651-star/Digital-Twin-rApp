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

## Limitations (read this)

The engine keeps the full multi-cell, multi-UE network, but it makes deliberate
simplifications. Be explicit about them when interpreting results:

1. **Static snapshot — no mobility.** One instant in time; no UE movement, Doppler,
   or fast fading. A consequence: **scheduling reduces to equal airtime** (a real
   proportional-fair / MAC scheduler only diverges from equal when the channel
   varies over time). So there is a single scheduling model (`equal`); there is no
   "real scheduler" mode, because it would be identical here and would require
   full-stack OAI + mobility.
2. **Inter-cell interference is modelled as noise.** Each UE's SINR uses
   `serving signal / (load · Σ other cells' power + noise)` — the standard
   "interference-as-noise" model (what a real UE receiver experiences, and what
   every system-level tool does). `neighbor_load` (0..1) scales neighbour activity;
   the default 1.0 is the full-buffer worst case. We do **not** have multiple cells
   physically transmit and combine their waveforms in the loop; true
   multi-cell-in-the-loop needs a GPU/FPGA channel emulator (NVIDIA Aerial /
   Colosseum), out of scope here.
3. **OAI is single-cell.** OAI (both the measured curve and the in-the-loop link)
   provides the **per-link** throughput realism; it does not compute inter-cell
   interference or cross-cell scheduling. Those stay on our (analytical) side.
4. **The throughput mapping is per-RE SINR + EESM through the OAI curve.** SINR is
   computed per resource element with channel-dependent MRT/MRC beamforming
   (`sigma_max(H_k)^2`, coherent — not a flat antenna-count bonus), then compressed
   to an AWGN-equivalent effective SINR with EESM (per-modulation betas,
   `eesm_beta_scale` as the calibration knob) before the OAI-measured MCS lookup —
   so frequency selectivity from the ray tracer survives into the throughput. The
   richer, exact-channel-per-link OAI throughput (real HARQ/decoding, iperf3
   goodput) is prototyped (exact-tap injection) but not yet the default output.
5. **Exact-channel injection caveats:** same taps applied to all antenna pairs
   (MIMO approximation), one link per run, and UL SNR is regulated by OAI power
   control so it doesn't expose the injected path loss (see `oai/README.md`).
6. **Network data is swappable; random by default.** Set `cells_csv` / `ues_csv`
   (WGS84 lat/lon rows, OpenCelliD-style; auto-sectorized unless `azimuth_deg` is
   given) to run a real site; otherwise cells/UEs/traffic are seeded-random
   stand-ins.
