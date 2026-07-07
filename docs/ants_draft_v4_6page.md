# An Open, Site-Specific, Multi-Cell 5G Digital Twin: Ray-Traced Throughput, an OpenAirInterface-Grounded Link Model, and a Traffic-Steering rApp

*Free-flow ~6-page IEEE draft. All numbers are from the released experiment harness
(`dtrapp/runner/sweep.py`): 3 urban scenes x 8 random seeds + an inter-cell-load
sweep. Figures referenced live in `experiments/results/`.*

## Abstract

Network digital twins are increasingly used to develop and validate O-RAN control
applications before deployment, but open platforms trade off protocol-stack
realism, site-specific propagation, network scale, and closed-loop control — none
combines all four. We present an open-source, CPU-only digital twin that (i) builds
a multi-cell, multi-user 5G scene from OpenStreetMap and ray-traces every
cell-to-user channel with NVIDIA Sionna RT; (ii) computes per-user downlink
throughput from a link model **measured on OpenAirInterface's (OAI) real physical
layer** rather than a closed-form formula, using per-resource-element SINR with
EESM link abstraction; (iii) hosts an O-RAN traffic-steering rApp that rebalances
load via cell-individual offsets; and (iv) grounds per-link realism by injecting
the exact ray-traced channel into a live OAI gNB-UE link. We evaluate across three
cities (Berlin, Paris, Manhattan) and eight random layouts each (24 runs). The
rApp raises **median per-user throughput by 9.5 ± 11.3%** and **served cell-edge
throughput by 22.4 ± 24.8%**, improves Jain fairness by 9.1%, and reduces peak
cell load by 0.75 users on average, while — honestly — leaving the aggregate rate
and the coverage-limited outage rate essentially unchanged (it balances load, it
does not create coverage). A configuration sweep shows per-user throughput rising
1.5-1.7x as inter-cell load falls from full to idle. The platform runs on a
commodity CPU and is released open-source.

## I. Introduction

The digital twin is emerging as the environment in which AI/ML-driven RAN control
(O-RAN rApps/xApps) is trained and validated before it touches a production
network. Its value hinges on the fidelity of the data it produces. Open tooling,
however, splits into camps that do not meet. System-level simulators (ns-3/5G-LENA,
Simu5G) scale to many cells but abstract the physical layer into formulas.
Protocol-stack emulators built on OpenAirInterface (OAI) execute the genuine 5G-NR
stack but, in published integrations with realistic propagation, cover a single
link. Commercial network digital twins (e.g., Rimedo Labs' NDT with the VIAVI
emulator) do close the rApp loop, but are proprietary.

Our position is that four capabilities matter simultaneously for a useful RAN
twin — a real protocol stack, a site-specific ray-traced channel, a multi-cell
network, and a closed control loop — and that no open platform combines them. This
paper contributes such a platform and, importantly, an **honest, statistically
rigorous** evaluation: multiple cities, multiple random layouts, mean ± std, and
outage reporting, rather than a single flattering scenario. Our contributions:

1. An open, CPU-only, multi-cell/multi-user twin whose throughput is grounded in
   OAI's measured PHY, driven by per-resource-element SINR + EESM.
2. A traffic-steering rApp evaluated over 24 runs across three cities, with
   robust statistics and explicit outage accounting.
3. Verified injection of the exact ray-traced channel into a live OAI link.
4. A reproducible experiment harness and results, released open-source.

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
OAI with Sionna RT for a faithful single gNB-UE link but is single-cell and only
monitors KPIs via FlexRIC. Tiny-Twin (UCSD) runs a real OAI stack for multiple UEs
on a CPU with a RIC loop, but on a single cell from replayed channel traces (it
lists inter-cell interference as future work). Orange's RIC-TaaP/ns-O-RAN and
OpenTwin close rApp loops across many cells — including, in OpenTwin, an
elegant twin-to-real KPM self-correction — but on ns-3's abstracted PHY, not a real
stack. Recent OAI+FlexRIC work closes handover loops across real cells but over the
air, without a site-specific ray-traced channel. Within OAI, an emerging
ray-tracing channel emulator with a Godot front-end feeds the virtual-time
simulator VRTSim; it targets the per-link channel component (multi-node is on its
roadmap), and is a natural backend our injection step can adopt. The asterisk on
our fourth axis is deliberate and discussed in Section VI: the four are integrated
as components of one platform, with the rApp loop evaluated on the analytical twin
and the real stack grounded per link — full rApp-driven multi-cell OAI is ongoing.

## III. System Architecture

**Geometry.** A WGS84 bounding box drives an OpenStreetMap (Overpass) query;
building footprints are extruded into a 3D Mitsuba scene with ITU materials.

**Network.** Cells and UEs come through a swappable data source: a seeded random
generator (N sites x 3 sectors, uniform UE drops) for controlled studies, or a
CSV source for real site coordinates (e.g., OpenCelliD).

**Channel.** Sionna RT places one transmitter per cell (3GPP sector pattern,
planar array, downtilt) and one receiver per UE, and computes the channel
frequency response for every cell-to-UE link over an OFDM resource grid.

**KPI engine.** Each UE associates to the strongest cell (biased by a
cell-individual offset, below). SINR is computed per resource element: the serving
signal uses channel-dependent matched-filter (MRT/MRC) beamforming,
sigma_max(H)^2; other cells enter as (load-scaled) frequency-selective
interference; thermal noise is k*T*B*NF. The per-RE SINR vector is compressed to an
effective SINR by EESM (per-modulation-order betas, calibratable via a single
scale factor) and mapped to a modulation-and-coding scheme through a link curve
**measured offline from OAI's `nr_dlsim`** (real LDPC/rate-matching). Each cell
shares airtime equally among its UEs (proportional-fair on a static full-buffer
snapshot reduces to equal share), giving per-UE and per-cell throughput.

**Traffic-steering rApp.** A load-balancing rApp reads the twin's per-UE
throughput and per-cell load and adjusts each cell's CIO, which biases association
(a UE attaches to the cell maximising RSRP + CIO) without changing the physical
channel — the standard O-RAN O1 control knob. The controller performs coordinate
ascent on the proportional-fair (sum-log-throughput) utility, line-searching each
cell's CIO until no cell improves.

**Real-stack grounding.** The twin exports the ray-traced channel; a bridge
converts each link to time-domain taps and injects them into a live OAI gNB-UE
link over the software radio simulator (a small patch to OAI's channel module).
The real stack then runs its PHY/MAC over the site-specific channel. A second
bridge writes each UE's twin-computed inter-cell interference as a per-client
noise floor, so a single-link OAI run can reflect its multi-cell context.

## IV. Experimental Setup

**Scenes.** Three ~300-450 m urban boxes: Berlin-Mitte (2,623 buildings),
Paris-Opera (121), Manhattan-Midtown (119). Each scene's geometry is fetched and
built once and reused across seeds.

**Random layouts (seeds).** For each scene we draw eight seeded layouts (3 sites x
3 sectors = 9 cells, 30 UEs, uniform placement), ray-trace each, and run baseline
association and the rApp — 24 runs total (323 s on one CPU server).

**Radio configuration.** 3.5 GHz, 20 MHz, 46 dBm, 4x1 BS array, UE NF 7 dB, 30 kHz
SCS, ray-tracing depth 3. Default inter-cell load = 1.0 (full-buffer worst case).

**Configuration sweep.** For one layout per scene we sweep the neighbour load
factor in {0, 0.25, 0.5, 0.75, 1.0} on the cached channel (no re-ray-tracing).

**Metrics.** Per-UE downlink throughput; median and mean; **served cell-edge** =
5th percentile among UEs with non-zero rate (robust to coverage holes); **outage
rate** = fraction of UEs with zero rate; Jain fairness; peak cell load. rApp gains
are reported as mean ± std over runs.

## V. Results

**A. Traffic-steering rApp (Table II, Fig. 1).**
Across all 24 runs, relative to strongest-cell association:

| Metric | Overall (24 runs) | Berlin | Paris | Manhattan |
|---|---|---|---|---|
| Median throughput gain | +9.5 ± 11.3% | +10.5 ± 6.6% | +4.5 ± 7.7% | +13.3 ± 15.6% |
| Served cell-edge gain | +22.4 ± 24.8% | +41.0 ± 28.1% | +6.0 ± 6.6% | +20.2 ± 19.6% |
| Jain fairness gain | +9.1 ± 11.0% | +11.2 ± 8.7% | +4.4 ± 4.7% | +11.5 ± 15.4% |
| Peak-load change (UEs) | -0.75 ± 0.78 | -0.88 | -0.50 | -0.88 |
| Mean throughput gain | +0.5 ± 5.8% | -0.7% | -0.3% | +2.5% |
| Outage change | 0.0 pts | 0.0 | 0.0 | 0.0 |

The rApp consistently helps the users a strongest-cell policy under-serves: median
and served cell-edge throughput rise, fairness improves, and the busiest cell
sheds load. The pooled per-UE CDF (Fig. 1) shifts right in its lower-middle region
while the top is unchanged. Three honest observations: (i) **aggregate** throughput
barely moves (+0.5%) — the proportional-fair objective trades sum for fairness,
occasionally slightly negative; (ii) **outage is unchanged** — steering relocates
covered users but cannot create coverage for users with no viable link; and
(iii) **variance is high** (std comparable to mean) — the benefit is strongly
layout-dependent, which is exactly why multi-seed evaluation is necessary and why a
single scenario would mislead.

**B. Coverage and outage (Fig. 2).** Mean UE outage is 16.2% at full load, and
scene-dependent (Berlin 8.8%, Manhattan 16.3%, Paris 23.8%), reflecting random
placement over the extent. For a fixed layout, outage is essentially
coverage-limited (path-loss-driven) and thus insensitive to inter-cell load, while
served users are interference-limited.

**C. Sensitivity to inter-cell load (Fig. 3).** As the neighbour load factor falls
from 1.0 to 0, mean per-UE throughput rises 1.5-1.7x (Berlin 13.6 to 22.7, Paris
14.9 to 25.2, Manhattan 11.9 to 22.0 Mbps), confirming served users are
interference-limited and that the twin captures the interference-throughput
trade-off a formula-only model would need calibrating for.

**D. Real-stack grounding.** OAI builds and runs on the same CPU host; a gNB-UE
link over the software radio simulator reports real PHY KPIs (downlink SNR ~15 dB,
MCS 9, target BLER). Injecting the exact ray-traced channel is confirmed in the
gNB log (`[RT] injected 4 taps ... channel_length=49`), and the link runs its
PHY/MAC (HARQ, link adaptation) over the site-specific channel. Absolute path loss
is masked by AGC and uplink power control in phy-test; the proof of grounding is
the injection and the multipath the link equalizes, not an absolute-level change.

## VI. Discussion and Limitations

We state these plainly. (1) The rApp closed loop is evaluated on the multi-cell
analytical twin; the OAI stack provides per-link ground truth and verified channel
injection but is not yet *driven* by the rApp in one running system — full
integration (multi-UE SA + FlexRIC + rApp control of OAI) is ongoing. (2)
Inter-cell interference is modelled as (frequency-selective) noise power, not
physically combined waveforms; waveform-level combining needs cluster/GPU/FPGA
emulators. (3) Results are a static snapshot; all cells share one carrier; the
evaluation is downlink. (4) rApp benefits are high-variance and layout-dependent;
we report distributions, not a single number. (5) Outage is not addressed by
steering. (6) Validation is stack-vs-model, not against field measurements; real
cell databases integrate through the same interface and are the natural next step.

## VII. Conclusion

We presented an open, CPU-only, site-specific, multi-cell 5G digital twin that
grounds throughput in OpenAirInterface's physical layer, hosts a traffic-steering
rApp, and transmits a real OAI link over the exact ray-traced channel. Across three
cities and eight random layouts each, the rApp improves median and cell-edge
throughput and fairness and relieves peak load, without inflating aggregate rate or
fixing coverage — an honest, reproducible result. To our knowledge it is the first
open platform to bring these four ingredients together on commodity hardware, with
full rApp-driven multi-cell OAI integration identified as the next step.

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
