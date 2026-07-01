# OAI engine — build, run, and extract KPIs (standalone)

A self-contained toolkit to build the **OpenAirInterface (OAI)** 5G-NR stack, run a
gNB↔UE link entirely in software (no radio hardware), and extract real PHY/MAC KPIs
to CSV. No other dependencies — this branch is OAI only.

## Prerequisites

- Ubuntu (24.04 works), x86_64, CPU is fine.
- `sudo` (for the build's system dependencies), `git`, `python3`.

## Quickstart

```bash
# 1) Build the full OAI engine (gNB + UE). ~10-15 min. Installs deps + builds.
bash oai/setup_oai.sh                 # -> ~/openairinterface5g/.../nr-softmodem, nr-uesoftmodem

# 2) Run a gNB + UE link (phy-test + rfsimulator, no hardware) for 30 s.
bash oai/run_phytest.sh 30            # -> oai_run/gnb.log , oai_run/ue.log

# 3) Parse the gNB log into a KPI table.
python3 oai/collect_kpis.py oai_run/gnb.log oai_run/kpis.csv
```

## What you get

`oai_run/kpis.csv`, one row per printed stats interval:

| column | meaning |
|--------|---------|
| `dir` | `DL` or `UL` |
| `rounds` / `errors` | HARQ rounds / decode errors |
| `bler` | block error rate (held ~0.10 by link adaptation) |
| `mcs` | modulation & coding scheme index the scheduler chose |
| `snr_db` | measured SINR (dB) |
| `nprb` | number of PRBs allocated |
| `goodput_mbps` | delivered throughput |

## Two things that MUST be right (container-safe)

1. **Build with GCC, not clang.** `setup_oai.sh` sets `CC=gcc CXX=g++` — clang crashes
   on OAI's MMX intrinsics (`Cannot select: x86mmx`). It also installs
   `libstdc++-14-dev` so linking works.
2. **Run the binaries as a NON-root user (no `sudo`).** Under `sudo`, OAI attempts
   real-time scheduling (`SCHED_FIFO`), which sandboxed containers forbid, and it
   crashes (`pthread_create` EPERM). As a normal user it skips RT scheduling and runs.
   `run_phytest.sh` therefore does **not** use `sudo`.

## Note on `goodput = 0`

In bare `phy-test` there is no user traffic, so `goodput` reads 0 even though the link
is up and SNR/MCS/BLER are real. Getting a non-zero throughput number is the next step
(bring up the UE's `oaitun` interface and run `iperf3`; the tun device needs
`CAP_NET_ADMIN`, which a sandbox may restrict).

## Files

- `setup_oai.sh` — clone + build the full OAI engine (GCC).
- `run_phytest.sh` — launch gNB + UE (phy-test + rfsim, non-root), capture logs.
- `collect_kpis.py` — parse the gNB log into `kpis.csv` + print a summary.

## Persistence on cloud

The OAI build (~1.6 GB) does not survive an ephemeral VM reset. To have it ready in
every cloud-agent run, have the environment config's startup run `bash oai/setup_oai.sh`
(or bake the build into the base image).
