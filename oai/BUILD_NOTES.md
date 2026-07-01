# OAI build & run — verified recipe (sandboxed CPU container)

This records exactly what worked to build **and run** OpenAirInterface (gNB + UE)
in a sandboxed cloud/CPU container, including two non-obvious fixes.

## Environment

- Ubuntu 24.04, CPU-only, `sudo` available.
- Sionna 2.0.1 present (`pip install sionna sionna-rt`).
- OAI not preinstalled — built from source (below).

## Build (must use GCC, not clang)

```bash
sudo apt-get install -y iperf3 ninja-build libstdc++-14-dev   # (noninteractive)
git clone --depth 1 https://gitlab.eurecom.fr/oai/openairinterface5g.git
cd openairinterface5g/cmake_targets
sudo -E DEBIAN_FRONTEND=noninteractive ./build_oai -I         # install deps
CC=gcc CXX=g++ ./build_oai --gNB --nrUE --ninja -c            # build (~10-15 min)
```

Outputs: `cmake_targets/ran_build/build/nr-softmodem` (gNB) and `nr-uesoftmodem` (UE).

### Fix 1 — the default compiler is clang, which cannot build OAI
`c++` here is **clang 18**, which crashes on OAI's MMX intrinsics:
`fatal error: error in backend: Cannot select: x86mmx = bitcast ...`
Force **GCC** with `CC=gcc CXX=g++`. Also install `libstdc++-14-dev` (the default
toolchain was missing the matching `libstdc++.so`, giving `cannot find -lstdc++`).

### Gotcha — `apt install iperf3` hangs on an interactive prompt
Use `DEBIAN_FRONTEND=noninteractive` (and `debconf-set-selections` for
`iperf3/start_daemon false`) or it blocks forever on the debconf question.

## Run (phy-test + rfsimulator) — do NOT use sudo

```bash
cd cmake_targets/ran_build/build
CONF=../../../ci-scripts/conf_files/gnb.band78.106prb.rfsim.phytest-dora.conf

# gNB (writes reconfig.raw / rbconfig.raw, acts as rfsim server):
./nr-softmodem -O $CONF --rfsim --phy-test --rfsimulator.[0].serveraddr server &

# UE (connect over the simulated radio; use the raw files the gNB wrote):
./nr-uesoftmodem --rfsim --phy-test --rfsimulator.[0].serveraddr 127.0.0.1 \
    --reconfig-file $(pwd)/reconfig.raw --rbconfig-file $(pwd)/rbconfig.raw &
```

### Fix 2 — run as a NON-ROOT user (no sudo)
OAI calls `has_cap_sys_nice()`; if the process HAS `CAP_SYS_NICE` (i.e. run under
`sudo`), it tries **real-time scheduling** (`SCHED_FIFO`), which this sandbox
**forbids** (`chrt -f 1` fails even as root; `ulimit -r` = 0). Result:
`pthread_create(): ret: 1` and `Exiting execution`.
Running as the normal user drops `CAP_SYS_NICE`, so OAI **skips RT scheduling** and
runs on ordinary threads — no crash. (The docs use `sudo`; that's wrong for this
sandbox.)

## Verified result

gNB + UE synchronize over the rfsimulator and produce live PHY/MAC KPIs. Example
gNB per-UE line with the UE attached (uplink SNR is now realistic):

```
UE 1234: ulsch_rounds .../... BLER 0.10000 MCS (0) 9 (Qm 2 ...) NPRB 50 SNR 22.2 (+2.2) dB ... goodput 0.00 Mbps
```

Observed KPIs: **SNR, MCS, BLER, HARQ rounds, NPRB, PRB usage** — the "real-stack"
data we want. DL/UL `goodput` reads 0.00 Mbps because **no user traffic is being
injected yet** (phy-test with no data source).

## Next steps

1. Inject traffic to get non-zero throughput: bring up the `oaitun_ue1` IP interface
   and run `iperf3` (needs `CAP_NET_ADMIN` for the tun device — check if the sandbox
   allows it; may require full-stack mode or a tun workaround).
2. Capture KPIs programmatically via **FlexRIC** (KPM) instead of scraping logs.
3. Feed our **Sionna RT channel** into the rfsimulator's channel model (OWDT).

## For persistent cloud-agent use

This build does not survive VM resets. To have OAI ready in every cloud-agent VM,
put the clone + `build_oai` (with `CC=gcc CXX=g++`) into the environment config's
base image / startup script.
