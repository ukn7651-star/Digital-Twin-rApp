# An Open, Real-Stack, Site-Specific Multi-Cell Digital Twin for Closed-Loop O-RAN rApp Validation

*(Free-flow ANTS draft. Preliminary pieces are marked [done]; the contribution still being built is marked [planned]. Results placeholders are [TBD].)*

## Abstract

Open-source wireless digital twins are becoming the preferred way to develop and validate O-RAN control applications (rApps/xApps) before touching a live network. But today's open twins force a compromise on one of four axes. Twins built on a real 5G protocol stack (OpenAirInterface) with ray-traced channels — such as the Open Wireless Digital Twin (OWDT) — are single-cell and only *monitor* KPIs; the CPU-native Tiny-Twin runs a real stack with a control loop but on a single cell with replayed channel traces; ns-3/O-RAN twins (e.g., Orange RIC-TaaP with Sionna RT) are multi-cell and closed-loop but abstract the physical layer; and real-stack multi-cell handover demonstrations run over the air, without a site-specific ray-traced channel. No open platform combines all four: a **real** protocol stack, a **site-specific ray-traced** channel, **multiple cells**, and a **closed rApp control loop**. We propose exactly that union. Our twin builds a multi-cell scene from OpenStreetMap, ray-traces every cell-to-user channel with Sionna RT, drives per-cell/per-user throughput through a link mapping measured from OpenAirInterface's own physical layer, injects each user's site-specific channel and computed inter-cell interference into a live OAI link, and exposes KPIs to an O-RAN rApp (traffic steering / cell-individual-offset) whose decisions act back on the emulated network. We report a working multi-cell analytical layer and verified per-link channel injection [done], and we target the closed-loop rApp result — the gain the twin predicts versus the gain the real stack delivers — as the headline evaluation [planned].

## I. Introduction

3GPP and O-RAN both position the network digital twin as the environment in which AI/ML-driven RAN automation is trained and validated before deployment. Commercially this is already a product: Rimedo Labs couples a proprietary network digital twin with the commercial VIAVI emulator to validate traffic-steering rApps, reporting double-digit throughput gains before any field trial. The open-source community, however, has no equivalent that combines protocol-stack realism, site-specific propagation, network scale, and a closed control loop in one platform.

The gap is not for lack of effort — it is that each open effort optimizes a different axis. The Open Wireless Digital Twin (OWDT) pairs OpenAirInterface (OAI) with Sionna RT for a faithful *single* gNB-UE link and monitors KPIs through FlexRIC, but does not model other cells or close a control loop. Tiny-Twin runs a real OAI stack for multiple UEs on commodity CPUs with a real-time RIC loop, but on a single cell and from *replayed* channel traces rather than a site-specific multi-cell scene. The Orange RIC-TaaP / ns-O-RAN effort integrates FlexRIC and Sionna RT for full closed-loop rApp testing across many cells, but on the ns-3 abstract physical layer, not a real stack. And recent OAI+FlexRIC handover demonstrations close a control loop across two real cells, but over the air, without a ray-traced site-specific channel.

This paper proposes the missing union: an open twin that is simultaneously **real-stack, site-specific ray-traced, multi-cell, and closed-loop**. Our contributions are (i) a multi-cell, multi-user twin that computes site-specific per-user throughput from ray tracing with a link mapping measured from OAI's real physical layer [done]; (ii) a method to give a single real-stack OAI link its multi-cell context by injecting the user's ray-traced channel together with its computed inter-cell interference as the link's noise floor [done for injection; interference-floor step planned]; and (iii) a closed-loop rApp (traffic steering via cell-individual offset) validated against the real stack, reporting the twin-predicted versus stack-measured gain [planned].

## II. Related Work and Positioning

*(See the four-axis comparison table.)* OWDT [Iye 2025] — real stack, RT, single cell, monitor only. Tiny-Twin [2026] — real stack, multi-UE, single cell, RIC loop, replayed traces; explicitly lists inter-cell interference as future work. Orange RIC-TaaP / ns-O-RAN + Sionna RT — multi-cell, closed-loop, but ns-3 abstract PHY. OAI+FlexRIC customized handover [ACM 2025] — real stack, two cells, closed-loop, but over-the-air (no site-specific RT channel). Sionna SYS provides multi-cell per-resource-element SINR analytically but is not a real protocol stack. Our platform is the first open twin to occupy all four axes at once.

## III. System Architecture

**Geometry and network.** A geographic bounding box drives an OpenStreetMap query; buildings are extruded into a 3D Mitsuba scene. Cells and UEs come through a swappable data source — seeded-random for controlled studies, or real sites via lat/lon CSV (OpenCelliD-style). [done]

**Ray-traced channel.** Sionna RT places one transmitter per cell and one receiver per UE and computes the channel frequency response for every cell-to-UE link over an OFDM grid. [done]

**Fast analytical layer (all cells/users, seconds).** Each UE associates to its strongest cell; per-resource-element SINR is computed with channel-dependent beamforming and per-subcarrier inter-cell interference (load-scaled), compressed by EESM, and mapped to throughput through an **OAI-measured** SINR-to-MCS curve obtained offline from OAI's nr_dlsim. This produces per-UE and per-cell throughput and the KPIs the rApp consumes. [done]

**Real-stack layer (sampled links).** For a chosen UE, its serving link's ray-traced taps are injected into a live OAI gNB-UE rfsimulator link (a small patch to OAI's channel module; verified in the gNB log). The novel bridge to multi-cell: the fast layer computes that UE's thermal-plus-inter-cell-interference power and applies it as the emulated link's noise floor (OAI's runtime telnet knob), so a single-link real-stack run reflects the multi-cell network it belongs to. Multiple UEs run as separate processes with per-client channels; real per-UE goodput is read via iperf3, KPIs via FlexRIC (E2SM-KPM). [injection done; interference-floor + multi-UE orchestration planned]

**Closed loop.** FlexRIC exposes KPIs to a traffic-steering rApp that adjusts cell-individual offsets; decisions are applied back to the emulated network and the KPIs re-measured. [planned]

## IV. Evaluation Plan

Scene: urban OpenStreetMap area, [N] cells, [M] UEs, 3.5 GHz, 20 MHz. Preliminary [done]: the fast layer completes the full pipeline in about a minute on a CPU-only server; mean per-UE downlink throughput [TBD] Mbps; the load factor shifts mean effective SINR by [TBD] dB. The OAI-measured link curve spans MCS 0-28; per-link ray-traced tap injection into the live rfsimulator is verified (taps loaded, HARQ running). Headline result [planned]: run a traffic-steering rApp closed-loop on the twin and report (a) the throughput/load-balancing gain it achieves and (b) the gap between the fast layer's predicted gain and the real-stack-measured gain — the fidelity a twin actually delivers on a control task, which no open platform has reported.

## V. Limitations

Inter-cell interference is modeled as (frequency-selective) noise power, not physically combined waveforms — appropriate for standard receivers and consistent with every system-level tool; waveform-level combining needs cluster/FPGA/GPU emulators (Colosseum, AODT). The real-stack layer validates a sample of UEs, not the whole population simultaneously (the fast layer covers the population). The current snapshot is static; mobility via OAI's virtual-time simulator is future work. rfsimulator is non-real-time, so goodput is a relative, not absolute-real-time, measure. Validation is stack-versus-model, not yet against field measurements.

## VI. Conclusion

Open wireless digital twins have advanced quickly, but each occupies a different corner of a four-axis design space — real stack, site-specific ray tracing, multi-cell, closed loop — and none occupies all four. We propose the union, reusing a working multi-cell ray-traced analytical layer and verified real-stack channel injection, and targeting a closed-loop traffic-steering rApp result with a reported twin-to-stack fidelity gap. The outcome is an open, reproducible analogue of the proprietary rApp-validation twins now emerging commercially.

## References (to be completed)

Sionna RT (arXiv:2303.11103); OpenAirInterface (Computer Networks 2025); FlexRIC (CoNEXT '21); OWDT (arXiv:2503.12177 / IEEE Access 2025); Tiny-Twin (arXiv:2601.08217); Orange RIC-TaaP / ns-O-RAN-flexric; OAI+FlexRIC customized handover (ACM 2025); ns-3 + Sionna RT (arXiv:2501.00372); Rimedo Labs O-RAN whitepapers (TS-rApp); 3GPP TS 38.214; 3GPP TS 38.106 (OCNG).
