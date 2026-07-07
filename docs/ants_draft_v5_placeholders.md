# An Open, Site-Specific, Multi-Cell 5G Digital Twin: Ray-Traced Throughput, an OpenAirInterface-Grounded Link Model, and a Closed-Loop Traffic-Steering rApp

*Working ~6-page IEEE draft — FULL intended structure. Verified results are inline
and final; full-stack integration results are marked **[PLACEHOLDER / TBD]** and
will be filled as the integration lands (targeted today). Verified numbers come
from `dtrapp/runner/sweep.py`; figures in `experiments/results/`.*

## Abstract

Network digital twins are increasingly used to develop and validate O-RAN control
applications before deployment, but open platforms trade off protocol-stack
realism, site-specific propagation, network scale, and closed-loop control — none
combines all four. We present an open-source, CPU-only digital twin that (i) builds
a multi-cell, multi-user 5G scene from OpenStreetMap and ray-traces every
cell-to-user channel with NVIDIA Sionna RT; (ii) computes per-user downlink
throughput from a link model **measured on OpenAirInterface's (OAI) real physical
layer**, using per-resource-element SINR with EESM link abstraction; (iii) hosts an
O-RAN traffic-steering rApp; and (iv) grounds per-link realism by injecting the
exact ray-traced channel into a live OAI gNB-UE link. Across three cities and eight
random layouts each (24 runs), the rApp raises **median per-user throughput by
9.5 ± 11.3%** and **served cell-edge throughput by 22.4 ± 24.8%**, improves Jain
fairness by 9.1%, and reduces peak cell load by 0.75 users, while leaving aggregate
rate and coverage-limited outage unchanged. A configuration sweep shows per-user
throughput rising 1.5-1.7x as inter-cell load falls to idle. **[PLACEHOLDER: with
the full-stack integration (multi-UE Standalone core, FlexRIC KPM, and the rApp
driving OAI in the loop), we further report real per-UE iperf3 goodput of [TBD] and
a twin-predicted-vs-stack-measured rApp gain gap of [TBD].]** The platform runs on
a commodity CPU and is released open-source.

## I. Introduction

The digital twin is emerging as the environment in which AI/ML-driven RAN control
(O-RAN rApps/xApps) is trained and validated before it touches a production
network, and its value hinges on data fidelity. Open tooling splits into camps that
do not meet: system-level simulators scale to many cells but abstract the PHY;
OAI-based emulators execute the real 5G-NR stack but, with realistic propagation,
cover a single link; commercial twins close the rApp loop but are proprietary.

Four capabilities matter simultaneously for a useful RAN twin — a real protocol
stack, a site-specific ray-traced channel, a multi-cell network, and a closed
control loop — and no open platform combines them. This paper contributes such a
platform with a statistically rigorous, honest evaluation. Contributions:

1. An open, CPU-only, multi-cell/multi-user twin whose throughput is grounded in
   OAI's measured PHY, driven by per-resource-element SINR + EESM.
2. A traffic-steering rApp evaluated over 24 runs across three cities, with robust
   statistics and explicit outage accounting.
3. Verified injection of the exact ray-traced channel into a live OAI link, plus a
   twin-to-OAI inter-cell-interference noise-floor bridge.
4. **[PLACEHOLDER]** A full-stack closed loop — multi-UE Standalone, FlexRIC KPM,
   and the rApp acting on OAI — with real per-UE goodput and a twin-to-stack
   fidelity gap ([TBD], targeted for the camera-ready).
5. A reproducible experiment harness and results, released open-source.

## II. Related Work

Table I positions the closest open efforts on the four axes.

| Platform | Real stack | Site-specific RT | Multi-cell | Closed-loop rApp |
|---|:---:|:---:|:---:|:---:|
| OWDT (2025) | yes | yes | no (single cell) | no (monitor only) |
| Tiny-Twin (2026) | yes | replayed traces | no (single cell) | yes |
| Orange ns-O-RAN / RIC-TaaP | no (ns-3 PHY) | yes | yes | yes |
| OpenTwin (2026) | no (ns-3 PHY) | no | yes | yes |
| OAI+FlexRIC handover (2025) | yes | no (over-the-air) | yes | yes |
| OAI VRTSim / RT channel emulator | yes | yes | (roadmap) | no (channel component) |
| **This work** | yes | yes | yes | yes* |

Every existing open platform is missing at least one axis. OWDT (Iye et al.) pairs
OAI with Sionna RT for a faithful single gNB-UE link but is single-cell and
monitor-only. Tiny-Twin (UCSD) runs a real OAI stack for multiple UEs with a RIC
loop, but single-cell from replayed traces (it lists inter-cell interference as
future work). Orange RIC-TaaP/ns-O-RAN and OpenTwin close rApp loops across many
cells — OpenTwin adds twin-to-real KPM self-correction — but on ns-3's abstracted
PHY. OAI+FlexRIC handover work closes loops across real cells but over the air,
without site-specific ray tracing. OAI's emerging ray-tracing channel emulator
feeds the virtual-time simulator VRTSim (multi-node on roadmap) and is a natural
backend for our injection. The asterisk on our fourth axis is deliberate
(Section VI): the four are integrated as components, with the rApp loop evaluated on
the analytical twin and the real stack grounded per link; full rApp-driven
multi-cell OAI is the in-progress integration reported in Section V-E.

## III. System Architecture

**Geometry.** A WGS84 bounding box drives an OpenStreetMap (Overpass) query;
footprints are extruded into a 3D Mitsuba scene with ITU materials.

**Network.** Cells and UEs come from a swappable source: a seeded random generator
(N sites x 3 sectors, uniform UE drops) or a CSV source for real coordinates
(e.g., OpenCelliD).

**Channel.** Sionna RT places one transmitter per cell (3GPP sector pattern,
planar array, downtilt) and one receiver per UE and computes the channel frequency
response for every cell-to-UE link over an OFDM grid.

**KPI engine.** Each UE associates to the strongest cell (biased by a
cell-individual offset). SINR is per resource element: the serving signal uses
channel-dependent MRT/MRC beamforming (sigma_max(H)^2), other cells enter as
load-scaled frequency-selective interference, thermal noise is k*T*B*NF. The per-RE
SINR is EESM-compressed and mapped to an MCS via a curve **measured from OAI's
`nr_dlsim`**. Each cell shares airtime equally among its UEs.

**Traffic-steering rApp.** A load-balancing rApp adjusts each cell's CIO (biasing
association without changing the channel — the O-RAN O1 knob) by coordinate ascent
on the proportional-fair (sum-log-throughput) utility.

**Real-stack grounding.** A bridge converts each link to time-domain taps injected
into a live OAI gNB-UE link (a patch to OAI's channel module); a second bridge
writes each UE's twin-computed inter-cell interference as a per-client OAI noise
floor, so a single-link OAI run reflects its multi-cell context.

## IV. Experimental Setup

**Scenes.** Berlin-Mitte (2,623 buildings), Paris-Opera (121), Manhattan-Midtown
(119); geometry fetched/built once per scene and reused across seeds.

**Random layouts.** Eight seeded layouts per scene (9 cells, 30 UEs) — 24 runs
(323 s, one CPU server). 3.5 GHz, 20 MHz, 46 dBm, 4x1 BS array, NF 7 dB, 30 kHz
SCS, RT depth 3, default inter-cell load 1.0.

**Configuration sweep.** Neighbour load factor in {0, 0.25, 0.5, 0.75, 1.0} on a
cached channel per scene.

**Metrics.** Per-UE throughput (median, mean); served cell-edge = 5th percentile
among served UEs; outage = fraction with zero rate; Jain fairness; peak cell load.

**[PLACEHOLDER] Full-stack setup (in progress).** OAI 5G Core (oai-cn5g, Docker) +
gNB (SA) + N UEs in network namespaces, each over its ray-traced channel and
interference noise floor; FlexRIC (E2SM-KPM) for KPI streaming; iperf3 per UE for
goodput; the rApp issues CIO/handover actions over the O1/telnet interface. Scale:
[TBD] UEs on a [TBD] host.

## V. Results

**A. Traffic-steering rApp (Table II, Fig. 1).** Across 24 runs vs strongest-cell:

| Metric | Overall | Berlin | Paris | Manhattan |
|---|---|---|---|---|
| Median throughput gain | +9.5 ± 11.3% | +10.5 ± 6.6% | +4.5 ± 7.7% | +13.3 ± 15.6% |
| Served cell-edge gain | +22.4 ± 24.8% | +41.0 ± 28.1% | +6.0 ± 6.6% | +20.2 ± 19.6% |
| Jain fairness gain | +9.1 ± 11.0% | +11.2 ± 8.7% | +4.4 ± 4.7% | +11.5 ± 15.4% |
| Peak-load change (UEs) | -0.75 ± 0.78 | -0.88 | -0.50 | -0.88 |
| Mean throughput gain | +0.5 ± 5.8% | -0.7% | -0.3% | +2.5% |
| Outage change | 0.0 pts | 0.0 | 0.0 | 0.0 |

The rApp helps the users a strongest-cell policy under-serves (median, cell-edge,
fairness) and sheds peak load; the pooled per-UE CDF (Fig. 1) shifts right in its
lower-middle region. Honestly: aggregate rate barely moves (fairness trade-off),
outage is unchanged (steering relocates covered users, it does not create
coverage), and variance is high (layout-dependent) — motivating multi-seed
evaluation.

**B. Coverage and outage (Fig. 2).** Mean UE outage is 16.2% at full load, and
scene-dependent (Berlin 8.8%, Manhattan 16.3%, Paris 23.8%). For a fixed layout,
outage is coverage-limited (path-loss-driven) and insensitive to inter-cell load,
while served users are interference-limited.

**C. Sensitivity to inter-cell load (Fig. 3).** As the neighbour load factor falls
from 1.0 to 0, mean per-UE throughput rises 1.5-1.7x (Berlin 13.6 to 22.7, Paris
14.9 to 25.2, Manhattan 11.9 to 22.0 Mbps).

**D. Real-stack grounding (single link).** OAI builds/runs on the same host; a
gNB-UE link reports real PHY KPIs (downlink SNR ~15 dB, MCS 9). Injecting the exact
ray-traced channel is confirmed in the gNB log (`[RT] injected 4 taps ...
channel_length=49`); the link runs PHY/MAC over the site-specific channel.

**E. Full-stack integration (IN PROGRESS — [PLACEHOLDER]).**

*E.1 Real per-UE goodput (multi-UE Standalone + iperf3).* [PLACEHOLDER TABLE:
per-UE downlink goodput for N UEs over their ray-traced channels; compare with the
analytical twin's predicted per-UE throughput.]

| UE | twin-predicted (Mbps) | OAI iperf3 goodput (Mbps) | rel. error |
|---|---|---|---|
| [TBD] | [TBD] | [TBD] | [TBD] |

*E.2 FlexRIC KPM monitoring.* [PLACEHOLDER: per-UE MCS/BLER/RSRP/throughput
streamed via E2SM-KPM during the run; sample time series.]

*E.3 Closed-loop rApp on OAI — fidelity gap.* [PLACEHOLDER: run the traffic-steering
rApp against the live multi-cell OAI stack; report the twin-predicted gain vs the
stack-measured gain — the headline "how faithful is the twin on a control task"
result.]

| Metric | twin-predicted gain | OAI-measured gain | gap |
|---|---|---|---|
| median throughput | +9.5% | [TBD] | [TBD] |
| served cell-edge | +22.4% | [TBD] | [TBD] |
| peak-load reduction | -0.75 UEs | [TBD] | [TBD] |

## VI. Discussion and Limitations

(1) The rApp closed loop is currently evaluated on the multi-cell analytical twin;
the OAI stack provides per-link ground truth and verified channel injection but is
not yet *driven* by the rApp in one running system — Section V-E reports this
integration as it lands. (2) Inter-cell interference is modelled as
(frequency-selective) noise power, not physically combined waveforms. (3) Static
snapshot; single carrier; downlink. (4) rApp benefits are high-variance and
layout-dependent (we report distributions). (5) Outage is not addressed by
steering. (6) Validation is stack-vs-model; field-measurement calibration is
future work.

## VII. Conclusion

We presented an open, CPU-only, site-specific, multi-cell 5G digital twin that
grounds throughput in OAI's physical layer, hosts a traffic-steering rApp, and
transmits a real OAI link over the exact ray-traced channel. Across three cities
and eight random layouts each, the rApp improves median and cell-edge throughput
and fairness and relieves peak load, without inflating aggregate rate or fixing
coverage. The full-stack closed loop (Section V-E) is the in-progress integration
that makes it the first open platform to bring all four ingredients together on
commodity hardware.

## References (to be completed)

Sionna RT (arXiv:2303.11103); OpenAirInterface (Computer Networks 2025); FlexRIC
(CoNEXT '21); OWDT (arXiv:2503.12177 / IEEE Access 2025); Tiny-Twin
(arXiv:2601.08217); OpenTwin (arXiv:2605.24662); Orange RIC-TaaP / ns-O-RAN-flexric;
OAI ray-tracing channel emulator + VRTSim (Eurecom GitLab; OAI Kista workshop 2025);
OAI+FlexRIC customized handover (ACM 2025); ns-3 + Sionna RT (arXiv:2501.00372);
Rimedo Labs O-RAN whitepapers (traffic steering); 3GPP TS 38.214; TS 38.306;
TS 38.106 (OCNG).

---
### Figures (in `experiments/results/`)
- `fig_cdf_pooled.png` — per-UE throughput CDF, baseline vs rApp (pooled).
- `fig_outage_vs_load.png` — UE outage vs inter-cell load, per scene.
- `fig_throughput_vs_load.png` — mean throughput vs inter-cell load, per scene.
- **[PLACEHOLDER]** `fig_goodput_twin_vs_oai.png` — twin-predicted vs OAI iperf3 goodput.
- **[PLACEHOLDER]** `fig_closed_loop_gap.png` — twin-predicted vs stack-measured rApp gain.
