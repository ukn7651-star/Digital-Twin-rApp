# Full-stack (multi-cell, closed-loop) workflow — run on a host

This is the end-to-end path that turns the analytical twin into a **multi-UE,
real-stack, closed-loop** setup: OAI Standalone core + gNB + multiple UEs, each
UE over its own ray-traced channel and inter-cell interference noise floor, with
the traffic-steering rApp driving handovers.

> **IMPORTANT — where this runs.** The steps below require a **full Linux host
> with root and Docker**, and are **not yet integration-tested end-to-end**.
> Everything on the *twin* side (channel export, interference-floor computation,
> rApp decision) is pure Python, unit-tested, and runs anywhere; the
> OAI/Docker/FlexRIC steps follow OAI's documented procedures and should be run on
> such a host. The single-UE phy-test path in `oai/README.md` runs on any CPU host
> and was used to verify the RT channel injection.

## What is verified where

| Component | Script / module | Verified end-to-end? |
|---|---|---|
| Twin channel export | `dtrapp.runner.cli` | Yes (needs OSM/Sionna) |
| Per-UE interference floor (noise trick) | `oai/interference_floor.py`, `dtrapp/oai_bridge.py` | Yes (unit-tested) |
| rApp decision -> handovers | `oai/rapp_closed_loop.py`, `dtrapp/rapp/` | Yes (unit-tested, dry run) |
| RT channel -> OAI taps | `oai/cfr_to_oai_channel.py` | Yes (single-UE phy-test) |
| OAI build + single link | `oai/setup_oai.sh`, `oai/run_phytest.sh` | Yes (built, ran, injection confirmed) |
| 5G core (SA) | `oai/setup_cn5g.sh` | No — needs Docker (host) |
| Multi-UE SA run | `oai/run_multi_ue_rfsim.sh` | No — needs root/netns (host) |
| FlexRIC + KPM xApp | `oai/setup_flexric.sh` | No — needs build toolchain (host) |
| Per-UE iperf3 goodput | `oai/iperf3_goodput.sh` | No — needs SA stack + CAP_NET_ADMIN (host) |

## Run order (on the host)

```bash
# 0) Twin: export the ray-traced channel (needs OSM + Sionna once).
python3 -m dtrapp.runner.cli configs/example.yaml         # -> output/channel/{cfr.npy,network.json}

# 1) Twin -> OAI bridges (pure Python, no host deps):
python3 oai/interference_floor.py output/channel          # -> interference_floor.conf (+ .csv)
python3 oai/cfr_to_oai_channel.py output/channel \
        --base-conf <SA gNB conf>                         # -> oai_rt_taps.txt, gnb conf

# 2) Build OAI (with telnet + E2 for control): ~10-15 min.
bash oai/setup_oai.sh
#   (build with: ./build_oai --gNB --nrUE --build-lib "telnetsrv e2" --ninja )

# 3) Bring up the 5G core (Docker):
bash oai/setup_cn5g.sh

# 4) (optional) Build FlexRIC + start the RIC and the KPM xApp:
bash oai/setup_flexric.sh

# 5) Run gNB + N UEs, each over its RT channel + interference floor:
#    (the gNB SA conf must @include interference_floor.conf; connection order
#     maps clients to rfsimu_channel_ue0, ue1, ...)
sudo NUE=3 GNB_CONF=/abs/gnb_sa.conf UE_CONF=/abs/ue.conf \
     OAI_RT_TAPS=$PWD/output/channel/oai_rt_taps.txt \
     bash oai/run_multi_ue_rfsim.sh 60

# 6) Measure per-UE downlink goodput:
sudo NUE=3 SERVER_IP=<CN data-net IP> bash oai/iperf3_goodput.sh

# 7) Close the loop: let the rApp steer load via handovers.
python3 oai/rapp_closed_loop.py output/channel --pci-map c0=0,c1=1,c2=2 \
        --apply --telnet-port 9090
```

## Notes / calibration
- `interference_floor.py` emits a per-UE *rise* over thermal; set OAI's per-client
  `noise_power_dB = baseline + rise` (`--baseline-noise-db` calibrates the
  interference-free level on your host).
- Absolute path loss is masked in rfsim by UE AGC and UL power control (see
  `oai/README.md`); use the SA link-adaptation KPIs (MCS/BLER/goodput) as the
  observable, not absolute RSRP.
- The rApp decision is computed on the twin; `--apply` executes it on the running
  stack via telnet N2 handovers. Map twin `cell_id` to gNB PCI with `--pci-map`.
