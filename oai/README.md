# OAI side — build, run, and bridge the Sionna RT channel

This is the **OpenAirInterface (OAI)** half of the digital twin. The `dtrapp`
package (Sionna RT) produces the site-specific channel; OAI (a real 5G-NR stack)
produces the throughput/KPIs over it. There is **no Sionna SYS** model anywhere.

```
dtrapp (Sionna RT):  OSM -> 3D scene -> ray-traced channel (CFR)  ->  output/channel/
OAI (this folder):   real gNB+UE stack over that channel          ->  real KPIs
```

## Prerequisites

- Ubuntu (24.04 works), x86_64, CPU is fine. `sudo` (for the build), `git`, `python3`.

## Quickstart

```bash
# 0) Generate the ray-traced channel with the RT side (needs sionna + sionna-rt):
python3 -m dtrapp.runner.cli configs/example.yaml   # -> output/channel/cfr.npy, network.json

# 1) Build the full OAI engine (gNB + UE). ~10-15 min.
bash oai/setup_oai.sh                               # -> ~/openairinterface5g/.../nr-softmodem, nr-uesoftmodem

# 2) Run a gNB + UE link (phy-test + rfsimulator, no hardware) for 30 s.
bash oai/run_phytest.sh 30                          # -> oai_run/gnb.log, ue.log

# 3) Parse the gNB log into a KPI table.
python3 oai/collect_kpis.py oai_run/gnb.log oai_run/kpis.csv

# 4) (bridge) Convert the RT channel into OAI channel taps.
python3 oai/cfr_to_oai_channel.py output/channel --taps 4   # -> output/channel/oai_taps.npz
```

Steps 1-3 run OAI over its **own** channel model (a good first check). Step 4 is the
**RT->OAI bridge**: it turns our ray-traced CFR into channel taps; feeding those taps
into the running rfsimulator is the remaining integration (see below).

## The RT -> OAI bridge (status)

`cfr_to_oai_channel.py` converts the exported CFR (frequency domain) into a few
time-domain **taps** (delay + complex gain) per cell->UE link — the form OAI's
channel emulator uses. **Producing the taps works.** Feeding them into the live
rfsimulator requires OAI's external-channel / channel-emulator interface (the
"OAI meets Sionna RT" / OWDT branch; see `NVlabs/sionna-rk`). That OAI-side
plumbing is the one piece still to wire up for a fully site-specific run.

## Files & KPIs

- `setup_oai.sh` — build the full OAI engine (GCC).
- `run_phytest.sh` — launch gNB + UE (phy-test + rfsim, **non-root**), capture logs.
- `collect_kpis.py` — parse gNB log -> `kpis.csv` (`dir, rounds, errors, bler, mcs, snr_db, nprb, goodput_mbps`).
- `cfr_to_oai_channel.py` — RT CFR -> OAI channel taps (bridge).

## Two container-safe rules (baked into the scripts)

1. **Build with GCC** (`CC=gcc CXX=g++`) — clang crashes on OAI's MMX intrinsics.
2. **Run OAI as a NON-root user** — under `sudo`, OAI tries `SCHED_FIFO`, which
   sandboxes forbid (crash); as a normal user it skips real-time scheduling.

## Notes

- Bare `phy-test` has no user traffic, so `goodput` reads 0 while SNR/MCS/BLER are
  real. Non-zero throughput needs `iperf3` over the UE's `oaitun` interface
  (needs `CAP_NET_ADMIN`, which a sandbox may restrict).
- The OAI build (~1.6 GB) is not in the repo and does not survive VM resets; for
  persistent cloud use, run `setup_oai.sh` from the environment config's startup.
