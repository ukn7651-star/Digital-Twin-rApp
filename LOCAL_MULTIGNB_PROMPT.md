# Standalone prompt — multi-gNB rApp-driven closed loop + measure the full fidelity gap

Copy the block below into a fresh Cursor Agent on your local machine (clone the repo,
`git checkout ants-submission`, then paste). It's self-contained.

> Host requirement (same as before): a **stock Linux kernel with SCTP + TUN**, Docker,
> and root/sudo. The single-gNB SA loop already runs from last time; this extends it to
> **two real cells** so the rApp can actually steer load across them.
>
> Realistic expectation: this is the hardest part (OAI rfsim multi-cell handover is
> research-grade). The prompt tells the agent to verify one real handover *before*
> scaling, to fall back gracefully, and to report honestly what works — do not expect
> or accept an overclaimed result.

---

```
You are an expert 5G/O-RAN + LaTeX engineer. Work autonomously, verify with runtime
evidence, and never fabricate a number (a reviewer already caught a fabricated stat in
this project — every value in the paper must be reproducible from committed data/logs).

## Mission
Extend this project's real-stack result from a single gNB to a MULTI-gNB, rApp-DRIVEN
closed loop, measure the full multi-cell fidelity gap over multiple layouts/configs
(with mean±std, like the existing sweeps), and update the paper. A prior agent measured
the LINK-dimension fidelity gap on one gNB (real iperf3 goodput vs twin link curve:
median 53% over-prediction; per-UE steering-gain gap 4.9 pts). The remaining step —
which reviewers will want — is the rApp actually moving UEs across >=2 real cells and
the DELIVERED gain measured vs the twin's prediction.

## Read first (recover full context from the repo)
- AGENTS.md (env; use `export CUDA_VISIBLE_DEVICES=""` for Sionna on CPU).
- oai/README_full_stack.md (integration runbook), oai/check_host.sh.
- paper/main.tex — esp. the subsection "The real fidelity gap" (Sec. \label{sec:realgap}).
- experiments/real_fidelity_gap.py (single-gNB driver) and experiments/sweep.py
  (multi-seed harness style to mirror), experiments/results/real_*.{csv,json}.
- dtrapp/rapp/ — run_traffic_steering() returns a decision; association_changes(baseline,
  steered) yields per-UE handovers {ue_id, from_cell, to_cell} (this IS the rApp action).

## What exists (build on it; don't redo)
- Analytical multi-cell twin + PF traffic-steering rApp (per-cell CIO).
- Single-gNB real SA loop verified (5G core healthy + gNB + UE PDU session + iperf3);
  ray-traced channel injection works; link-dimension fidelity gap measured.
- OAI has 2-cell configs already: ci-scripts/conf_files/gnb-du.sa.band78.106prb.rfsim.pci0.conf
  and .pci1.conf (two DUs, PCI 0 and 1), plus gnb.sa.band78.106prb.rfsim.flexric.conf
  (E2-enabled). These are the basis for a 2-cell topology.

## Phase 0 — host + reuse
- `bash oai/check_host.sh` must say READY. Bring the 5G core back up
  (`cd ~/oai-cn5g && sudo docker compose up -d`; all NFs healthy).
- Rebuild OAI with control libs if not already: `--build-lib "telnetsrv e2"`.

## Phase 1 — stand up TWO real cells
- Preferred: CU + DU-pci0 + DU-pci1 over F1 (one gNB, two cells) on the same core.
  Configure both DUs (PLMN 001/01, AMF 192.168.70.132, host bridge IP). Start CU, both
  DUs, one UE; verify the UE registers and is served by cell 0 (PCI 0).
- Fallback: two monolithic gNBs + Xn handover on the same core.

## Phase 2 — verify ONE real handover (KEY MILESTONE — do not scale until this works)
- Trigger a handover of the UE from cell 0 -> cell 1. Try, in order:
  (a) measurement-triggered A3 event with a CIO offset; (b) an explicit CU/telnet
  handover command; (c) FlexRIC E2 RC (RAN Control) handover.
- REQUIRED evidence: CU/gNB log shows the handover executing; the UE is then served by
  PCI 1; the PDU session is preserved (oaitun IP stays); iperf3 goodput continues on the
  new cell. Capture these to a log. If none of (a)-(c) works in rfsim, STOP and report
  exactly what failed — do not proceed to fake a loop.

## Phase 3 — multi-UE on the 2-cell topology
- Run N UEs; give each its per-UE ray-traced channel + interference floor
  (python3 oai/interference_floor.py output/channel; python3 oai/cfr_to_oai_channel.py ...;
  connection order maps to rfsimu_channel_ue0, ue1, ...). Baseline = strongest-cell.

## Phase 4 — rApp DRIVES the steering
- Per layout: compute the twin's decision (run_traffic_steering -> association_changes)
  = the set of UEs to move cell A->B. Apply exactly those handovers on the real stack
  (autonomous E2-RC preferred; scripted CU/telnet trigger is acceptable — STATE which you
  used in the paper). Measure per-UE downlink iperf3 goodput BEFORE (baseline association)
  and AFTER (rApp-steered association).

## Phase 5 — sweep + statistics (like the other experiments)
- Write experiments/multignb_fidelity_gap.py that automates Phases 3-4 over >=8 layouts
  (random seeds on the built Berlin scene; optionally 2-3 inter-cell load configs) and
  aggregates: REAL rApp gain (median/served-edge/mean per-UE, mean±std), the twin-PREDICTED
  gain for the same layouts, and the FIDELITY GAP per metric (twin - real, mean±std).
- Outputs: experiments/results/multignb_fidelity_gap.{csv,json} + paper/fig_multignb_gap.png
  (twin-predicted vs real multi-cell rApp gain, y=x line). Support --skip-measure to
  recompute analysis from the committed CSV without touching OAI.

## Phase 6 — update the paper (loop now closed)
- New/expanded Results subsection "Full multi-cell closed loop": the real multi-cell rApp
  gain vs twin prediction, with stats + fig_multignb_gap.png. Update the abstract,
  contributions (the closed loop is now DONE, not per-link), the related-work table
  footnote (drop the "*" caveat ONLY if the loop is genuinely closed), the
  Discussion/Limitations (remove the single-gNB caveat; add any new honest ones), and the
  Conclusion. Keep 6 pages (IEEEtran conference); compile:
  `cd paper && pdflatex main && bibtex main && pdflatex main && pdflatex main` (0 errors,
  no undefined refs, no overfull boxes).

## Correctness + honesty (STRICT)
- Every number must be reproducible from experiments/results/* or OAI logs. No invented stats.
- Prove the handover really happened (logs + PCI change + preserved PDU session + iperf3 on
  the new cell) before claiming a closed loop.
- If rfsim multi-cell handover is flaky, report partial results honestly (e.g., "k of 8
  layouts completed") rather than overclaiming. A smaller real result beats a fake big one.
- If you used a scripted trigger rather than autonomous E2-RC, say so explicitly in the paper.
- Keep the single-gNB link-fidelity result; the multi-cell result complements it.

## Graceful fallbacks (use only if needed, and document them)
- CU+2DU F1 handover failing -> try 2 gNBs + Xn.
- Autonomous A3/CIO trigger too fiddly -> scripted handover of the rApp's chosen UEs.
- A UE cannot be dual-cell-reachable in rfsim -> serve each UE on the rApp-assigned cell
  vs its strongest cell and compare goodput; document this as the method.

## Evidence + git
- Save logs/figures under experiments/results/; keep the stack running for inspection.
- Commit in logical chunks; push to ants-submission; update the PR. Do NOT force-push or
  merge unrelated histories.

## Definition of done
A real >=2-cell OAI SA stack with the rApp's steering applied and VERIFIED (handover in
logs, PDU session preserved, iperf3 on the new cell); per-UE goodput measured baseline vs
steered over >=8 layouts (mean±std); the real multi-cell rApp gain and the twin-vs-real
fidelity gap computed and written to experiments/results/multignb_fidelity_gap.*; the paper
updated (loop closed) and compiling clean to 6 pages; everything committed and pushed.
```
