# OAI integration — runbook & design

Goal: replace the **modeled** throughput stage (Sionna SYS) with **OpenAirInterface
(OAI)**, a real 5G-NR protocol stack, so throughput/KPIs come from a real scheduler,
real LDPC decoding, and real HARQ instead of a link-level model. Our **Sionna RT ray
tracing stays** and provides the channel OAI transmits through.

> Status: **exploration**. This document is the plan/runbook; the OAI build itself is
> a separate C project and is **not** vendored into this repo. Command lines below are
> representative — confirm exact flags against the current OAI docs (they evolve).

---

## 1. Where OAI fits (the one picture)

```
  positions/config ──► Sionna RT ──► channel (CFR) ──►  [ throughput engine ]  ──► throughput / KPIs
    (our side)         (KEEP)         dtrapp.compute_cfr        ▲
                                                               │
                                          today:  Sionna SYS  (a MODEL / formula)
                                          plan:   OAI         (a REAL 5G stack)
```

- OAI **needs a channel as input** and **has no map/positions of its own** — so it
  improves the *throughput data*; the geometry/positions stay on our side.
- OAI is a real-stack replacement for the `dtrapp/kpi/sys_link.py` box: same
  "channel in → throughput out", but run through actual protocol software.
- The channel we feed OAI is our ray-traced one, produced today by
  `SionnaPropagationEngine.compute_cfr()` in `dtrapp/propagation/sionna_engine.py`.

Two ways to use OAI (alternatives, decided later by speed):
- **A) OAI in the loop** — OAI computes throughput for every scenario. Most realistic,
  slow (real-time stack).
- **B) OAI as a calibrator** — keep the fast SYS model for bulk dataset generation,
  use OAI offline to validate/calibrate it.
Both start with the same first step (feed our channel into OAI, extract data).

---

## 2. Prerequisites

- Linux (Ubuntu is best-supported by OAI). A recent x86_64 machine.
- Build tools + OAI dependencies (installed by OAI's own script, see step 1).
- `iperf3`, `ping` for throughput/latency.
- Our engine + Sionna (`pip install sionna sionna-rt`) for the channel side.
- CPU is fine for small scenes; if a GPU is present but too old for Sionna, force CPU
  on the Sionna side with `export CUDA_VISIBLE_DEVICES=""` before importing sionna.

---

## 3. Step 1 — Build OAI

```bash
git clone https://gitlab.eurecom.fr/oai/openairinterface5g.git
cd openairinterface5g/cmake_targets
./build_oai -I            # one-time: install system dependencies (needs sudo)
./build_oai --gNB --nrUE  # build the gNB (nr-softmodem) and UE (nr-uesoftmodem)
```

Produces `nr-softmodem` (gNB) and `nr-uesoftmodem` (UE) under
`cmake_targets/ran_build/build/`.

---

## 4. Step 2 — Bring up a UE↔gNB link in the RF simulator (phy-test)

`phy-test` = single UE, no core, a forced data channel — fastest way to get PHY data.
`rfsim` = no radio hardware; the two programs exchange IQ samples over a socket.

Terminal 1 (gNB, acts as rfsim server):
```bash
sudo ./nr-softmodem -O <gnb.conf> --rfsim --phy-test \
     --rfsimulator.serveraddr server --noS1
```

Terminal 2 (UE, connects to the gNB; run in its own network namespace):
```bash
sudo ./nr-uesoftmodem -O <ue.conf> --rfsim --phy-test \
     --rfsimulator.serveraddr <gnb_ip> --noS1
```

Success = a working PDSCH and a `oaitun_ue1` network interface appears.
(See the open-cells "5G OpenAir first run" tutorial for the namespace setup.)

---

## 5. Step 3 — Measure throughput + read PHY/MAC KPIs

- Throughput (end-to-end) over the UE tunnel interface:
  ```bash
  iperf3 -s                       # on the gNB/core side
  iperf3 -c <server_ip> -B <oaitun_ue1 ip>   # from the UE side
  ping -I oaitun_ue1 <gnb_ip>     # latency
  ```
- PHY/MAC KPIs (MCS, BLER, CQI, PRB, RSRP): enable L1/MAC stats / the built-in scope
  in the gNB (`--stats` options / config), or use the community scripts
  (`mbozis/OAI_5G_scripts`, `oaitest --monitor`).

These are the "improved data": protocol-accurate throughput + MCS/BLER/etc.

---

## 6. Step 4 — Structured KPI capture

Two cleaner options than scraping logs:
- **T-Tracer + Data Recording app → SigMF datasets.** Traces (PUSCH IQ, channel
  estimates, bits) stream over TCP (ports 2021 gNB / 2023 UE); selected via
  `common/utils/data_recording/config/config_data_recording.json`; saved in the
  standard SigMF format. (OAI "Data Recording" docs.)
- **FlexRIC (O-RAN near-RT RIC).** Build FlexRIC, connect it to the gNB over E2, and
  subscribe to the **KPM** service model to stream KPIs (throughput, MCS, BLER, PRB,
  RSRP) programmatically. This is the production-grade data tap.

---

## 7. Step 5 — Bridge: feed our Sionna RT channel into OAI (the OWDT approach)

Reference design: **"Open Wireless Digital Twin: OpenAirInterface meets Sionna RT"**
(arXiv 2503.12177). RT-generated channel impulse responses (CIRs) are fed into OAI's
channel emulator via real-time convolution (their build uses a 4-tap CIR
approximation on CPU).

Mapping to our code:
- Our `compute_cfr()` already produces the ray-traced channel per cell→UE. We need to
  convert it to the **CIR form OAI's channel emulator expects** (taps: delays +
  complex gains), matching OAI's rfsim external-channel interface.
- Start point: NVIDIA **Sionna Research Kit** (`NVlabs/sionna-rk`) and the OAI
  "ch-emu / OAI-meets-Sionna" branch — reuse their channel-injection code rather than
  writing convolution from scratch.

Deliverable of this step: OAI producing throughput/KPIs over *our* site-specific
channel (not OAI's built-in statistical models).

---

## 8. Step 6 — Dataset export (optional, for ML training)

If the data is meant to train ML models, standardize it in the **DeepMIMO** format
(`pip install deepmimo`) — it has a Sionna RT converter and feeds Sionna PHY/SYS and
MATLAB. Decide features/labels from the target ML task (throughput prediction /
localization / beam selection) before mass-generating.

---

## 9. Glue code to live here (planned)

- `run_oai_rfsim.sh` — bring up gNB+UE in phy-test/rfsim.
- `collect_kpis.py` — parse OAI stats / SigMF / FlexRIC output → tidy CSV/JSON.
- `cfr_to_oai_channel.py` — convert `compute_cfr()` output → OAI channel (CIR) input.
- `oai_vs_sys.py` — (calibration mode) run both on the same channel and compare.

---

## References

- Open Wireless Digital Twin (OAI + Sionna RT): arXiv 2503.12177 (IEEE Access 2025).
- NVIDIA Sionna Research Kit: github.com/NVlabs/sionna-rk.
- OpenAirTwin (Sionna RT DT + DeepMIMO export): github.com/HKUOpenSource/OpenAirTwin.
- OAI Data Recording (T-tracer → SigMF): OAI docs `usage/data_recording`.
- OAI first run / rfsim tutorial: open-cells.com "5G OpenAir first run".
- Sim2Field (training AI-RAN on DT data): arXiv 2509.23528.
- Digital-Twin-aided Massive MIMO CSI feedback (twinning fidelity): IEEE TComm 2025.
- DeepMIMO v4: deepmimo.net.
