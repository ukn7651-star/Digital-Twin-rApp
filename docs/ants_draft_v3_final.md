# An Open Site-Specific Multi-Cell 5G Digital Twin with Ray Tracing, an OpenAirInterface-Grounded Link Model, and a Traffic-Steering rApp

## Abstract

We present an open-source, CPU-only digital twin that evaluates 5G downlink performance for a multi-cell, multi-user network on a site-specific, ray-traced channel, and closes a control loop with an O-RAN traffic-steering application (rApp). A 3D scene is built from OpenStreetMap buildings; NVIDIA Sionna RT computes the channel for every cell-to-user link; per-user and per-cell throughput are obtained from a link model measured on OpenAirInterface's own physical layer rather than from a closed-form formula; and a load-balancing rApp adjusts per-cell cell-individual offsets (CIO) to steer cell-edge users toward lightly loaded neighbours. On an urban scene of 2,623 buildings with 9 cells and 30 users, the rApp raises aggregate downlink throughput by 7.1%, cell-edge (5th-percentile) throughput by 22.2%, and Jain's fairness by 8.3%, while reducing the peak cell load from 9 to 7 users. To ground the per-link realism, the exact ray-traced channel is injected into a live OpenAirInterface gNB-UE link running over the software radio simulator, and we confirm the real stack transmits over the site-specific channel and reports physical-layer KPIs. The entire platform runs on a commodity CPU server and is released as open source.

## I. Introduction

Digital twins are increasingly used to develop and validate O-RAN control applications before deployment. Existing open twins, however, each trade off one capability. The Open Wireless Digital Twin (OWDT) pairs OpenAirInterface (OAI) with Sionna RT for a faithful single-cell, single-user link but only monitors KPIs. Tiny-Twin runs a real OAI stack for multiple users on a CPU with a control loop, but on a single cell and from replayed channel traces. The Orange RIC-TaaP / ns-O-RAN effort closes rApp loops across many cells with Sionna RT, but on ns-3's abstracted physical layer. Recent OAI+FlexRIC demonstrations close handover loops across real cells, but over the air, without a site-specific ray-traced channel. None combines site-specific ray tracing, a multi-cell/multi-user network, a physical-layer-grounded link model, and a closed control loop in one open, CPU-only platform.

This paper presents such a platform. Its contributions are: (1) a site-specific, multi-cell, multi-user twin whose throughput mapping is measured from OAI's real physical layer (`nr_dlsim`) and driven by per-resource-element SINR with EESM link abstraction; (2) a traffic-steering / load-balancing rApp that runs a closed proportional-fair control loop on the twin, with quantified gains on a real urban scene; and (3) verified injection of the exact ray-traced channel into a live OAI gNB-UE link, grounding the twin's per-link realism in a real protocol stack. All components are open source and run on a commodity CPU.

## II. System Architecture

**Geometry and channel.** A geographic bounding box drives an OpenStreetMap query; buildings are extruded into a Mitsuba scene. Sionna RT places one transmitter per cell and one receiver per user and computes the channel frequency response for every cell-to-user link over an OFDM resource grid.

**Multi-cell KPI engine.** Each user associates to the strongest cell (biased by CIO, see below). Per-resource-element SINR uses channel-dependent matched-filter beamforming for the serving link and treats other cells as (load-scaled, frequency-selective) interference; the per-subcarrier SINRs are compressed to an effective SINR by EESM and mapped to a modulation-and-coding scheme through a link curve measured offline on OAI's `nr_dlsim`. Each cell shares its airtime among its users, giving per-user and per-cell throughput.

**Traffic-steering rApp.** A load-balancing rApp reads the twin's per-user throughput and per-cell load and adjusts each cell's CIO, which biases association (a user attaches to the cell maximising RSRP + CIO) without changing the physical channel - the standard O-RAN O1 control knob. The controller performs coordinate ascent on the proportional-fair utility (sum of log-throughput): for each cell it line-searches the CIO that best raises utility, sweeping until no cell improves. The physical channel is fixed throughout; only user-to-cell association changes.

**Real-stack grounding.** The twin exports the ray-traced channel; a bridge converts each link's channel to time-domain taps and injects them into a live OAI gNB-UE link over the software radio simulator (a small patch to OAI's channel module). The real stack then runs its physical and MAC layers over the site-specific channel, from which physical-layer KPIs (SINR, MCS, BLER) are read.

## III. Results

**Scene.** Central Berlin, 2,623 OpenStreetMap buildings, 3 sites x 3 sectors (9 cells), 30 users, 3.5 GHz, 20 MHz, 46 dBm, 4x1 base-station arrays. The full pipeline (geometry to KPIs) runs in about one minute on a CPU-only server.

**Traffic-steering rApp.** Starting from strongest-cell association (peak cell load 9 users), the rApp applies four CIO control actions and converges to a balanced configuration:

| Metric | Baseline | With rApp | Gain |
|---|---|---|---|
| Aggregate throughput | 373.0 Mbps | 399.4 Mbps | +7.1% |
| Mean per-user throughput | 12.43 Mbps | 13.31 Mbps | +7.1% |
| Cell-edge (5th pct) throughput | 1.33 Mbps | 1.62 Mbps | +22.2% |
| Jain's fairness | 0.531 | 0.576 | +8.3% |
| Peak cell load | 9 | 7 | -2 users |

The gains concentrate on lower-throughput users (the per-user throughput CDF shifts right in its lower half while the top is unchanged), i.e. the rApp helps cell-edge users a plain strongest-cell association starves, without sacrificing aggregate throughput.

**Real-stack grounding.** A live OAI gNB-UE link over the software radio simulator reports real physical-layer KPIs (downlink SNR ~15 dB, MCS 9, BLER 0.1). Injecting the exact ray-traced channel is confirmed in the gNB log — `[RT] injected 4 taps into rfsimu_channel_ue0 (channel_length=49)` — and the link runs its physical/MAC layers (HARQ, link adaptation) over the site-specific channel.

## IV. Limitations

Inter-cell interference is modeled as (frequency-selective) noise power rather than physically combined waveforms, consistent with system-level practice; waveform-level combining needs cluster/FPGA/GPU emulators. The rApp control loop runs on the multi-cell analytical twin, while the OAI stack provides per-link ground truth and verified site-specific channel injection; a full rApp-in-the-loop on the multi-cell stack requires multi-cell OAI with FlexRIC. In the software-radio-simulator, per-user application goodput requires a traffic generator over the tunnel interface (elevated privileges), so we report physical-layer KPIs there. The scene is a static snapshot; all cells share one carrier; the evaluation is downlink. The network layout is representative; real cell databases integrate through the same interface.

## V. Conclusion

We presented an open, CPU-only, site-specific multi-cell 5G digital twin that grounds its throughput in OpenAirInterface's physical layer, closes a traffic-steering rApp loop with measurable cell-edge and fairness gains, and transmits a real OAI link over the exact ray-traced channel. It is, to our knowledge, the first open platform to combine site-specific ray tracing, a multi-cell network, a physical-layer-grounded link model, and a closed rApp loop on commodity hardware.

## References (to be completed)

Sionna RT (arXiv:2303.11103); OpenAirInterface (Computer Networks 2025); FlexRIC (CoNEXT '21); OWDT (arXiv:2503.12177 / IEEE Access 2025); Tiny-Twin (arXiv:2601.08217); Orange RIC-TaaP / ns-O-RAN-flexric; OAI+FlexRIC customized handover (ACM 2025); ns-3 + Sionna RT (arXiv:2501.00372); Rimedo Labs O-RAN whitepapers (traffic steering); 3GPP TS 38.214; 3GPP TS 38.106 (OCNG).
