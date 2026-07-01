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

## The RT -> OAI bridge (working, exact complex taps)

OAI transmits over the **exact ray-traced channel**. `setup_oai.sh` applies a small
patch (`patches/rt_channel_injection.patch`) that adds `oai_rt_inject_channel()` to
OAI's `random_channel()`. When the env var `OAI_RT_TAPS` is set, that function
overrides the rfsimulator's sample-spaced impulse response (`channelDesc->ch`) with
the complex taps exported from Sionna RT, so the gNB<->UE link runs over the
site-specific channel instead of a statistical model.

```bash
# CFR -> exact taps (oai_rt_taps.txt) + channel-enabled gNB/UE confs:
python3 oai/cfr_to_oai_channel.py output/channel \
    --base-conf ~/openairinterface5g/ci-scripts/conf_files/gnb.band78.106prb.rfsim.phytest-dora.conf

# run OAI over the ray-traced channel:
OAI_RT_TAPS=output/channel/oai_rt_taps.txt \
CONF=output/channel/gnb_rtchan.conf bash oai/run_phytest.sh 30
```

**Verified** in the gNB log:

```
[OCM] [RT] injected 4 taps into rfsimu_channel_ue0 (path_loss_dB=0.00, channel_length=97, pairs=1)
```

i.e. the 4 dominant RT taps (and their delays -> sample positions) are loaded into
the live channel and the link runs over them (MCS/BLER/HARQ flowing).

### How the bridge builds the taps
1. IFFT the CFR per link -> CIR; keep the strongest causal taps (delay + complex gain).
2. Normalize the taps to **unit energy** so their shape carries the multipath; the
   overall link gain is carried separately by `path_loss_dB`.
3. Convert each tap delay (ns) to a sample index using the channel's sample rate; the
   patch allocates `channel_length` to fit.

### Calibration note (path loss vs. power control)
`path_loss_dB` is applied by OAI in `rxAddInput()` as `pow(10, path_loss_dB/20)`.
On the **uplink**, OAI's closed-loop power control regulates the received SNR to a
target, so steady-state UL SNR does **not** expose `path_loss_dB` (this is correct 5G
behavior, not a bug) — attenuation is compensated until the UE hits max power, then
the link degrades. The multipath *shape* from RT still affects equalization / effective
SINR. To observe path loss directly, use the **downlink** at the UE (no such loop):
`cfr_to_oai_channel.py` also emits `ue_rtchan.conf`, and `run_phytest.sh` accepts
`UE_CONF=...` to enable the DL channel model on the UE side (experimental in phy-test).

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
