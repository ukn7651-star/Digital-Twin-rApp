# Standalone prompt — Option B: controlled multi-cell fidelity gap (per-cell RT channel injection)

Paste the block below into a fresh Cursor Agent on your local machine (clone the repo,
`git checkout ants-submission`, then paste).

> Prereqs: the same SCTP+TUN host, Docker, root. The multi-gNB closed loop already
> works (CU + 2 DUs over F1, scripted `ci trigger_f1_ho`, 8/8 handovers). What's missing
> is that the two DUs ran a **clean** channel, so the twin (ray-traced SINR) and the real
> gains **decorrelated** (opposite sign in 7/8 layouts; the paper currently frames this
> honestly as "per-cell channel grounding needed"). Option B fixes exactly that.
>
> Safety net: an Option-A backup branch `cursor/ants-submission-optiona-backup-f4bc`
> holds the current submission-ready paper. If Option B doesn't pan out, revert to it.

---

```
You are an expert 5G/O-RAN + LaTeX engineer. Work autonomously, verify with runtime
evidence, and NEVER fabricate a number (a reviewer already caught a fabricated stat here;
every value in the paper must be reproducible from committed data/logs).

## Mission
Turn the multi-cell fidelity gap from a CONFOUNDED comparison into a CONTROLLED one, by
injecting each UE's ray-traced channel on BOTH real cells (DUs) so the live 2-cell OAI
stack experiences the same site-specific SINR the twin uses. Then measure the twin-vs-real
rApp steering gain over multiple layouts, and update the paper. If it works, this upgrades
the multi-cell result from "verified capability" to a genuine "measured multi-cell gap".

## Read first (recover context)
- AGENTS.md; oai/README_full_stack.md; oai/check_host.sh.
- paper/main.tex — Sec. \ref{sec:realgap} (single-gNB gap) and Sec. \ref{sec:multignb}
  (the current, honestly-caveated multi-cell result you will replace/upgrade).
- experiments/multignb_fidelity_gap.py (current driver), experiments/real_fidelity_gap.py.
- oai/cfr_to_oai_channel.py (CFR -> OAI taps; single link today) and
  oai/interference_floor.py (per-UE noise floor). dtrapp/rapp/ (run_traffic_steering,
  association_changes). The twin CFR is [ue, ue_ant, cell, bs_ant, sym, sc] — it has each
  UE's channel to EVERY cell.

## Why the current multi-cell number is confounded (fix this)
The two DUs used a clean rfsim channel, so which cell is "better" on the real stack was NOT
the ray-traced SINR the twin optimized on. Result: twin gain (66% mean) vs real (9%),
opposite sign in 7/8 layouts, std 165. To make the comparison valid, each DU must present,
per UE, that UE's ray-traced channel + relative path loss TO THAT DU's cell.

## Core technical task
1. Extend oai/cfr_to_oai_channel.py (or add oai/cfr_to_oai_multicell.py) to emit, per DU,
   a per-client channel: for the 2-cell topology (DU-pci0 = twin cell c0, DU-pci1 = cell c1),
   write TWO taps files:
     - du0 taps: for each UE u (client order ue0, ue1, ...), the CFR taps of link u->c0 and
       the relative path-loss (link gain) of u->c0.
     - du1 taps: same for u->c1.
   Use the existing tap extraction (IFFT -> strongest causal taps, unit-energy) and the
   relative-path-loss convention already in cfr_to_oai_channel.py, but PER (UE, cell) rather
   than one strongest link. Each DU's rfsim connection order maps clients to ue0, ue1, ...
2. Start DU-pci0 with its taps file and DU-pci1 with its taps file (each DU is its own
   rfsim server / process, so each reads its own OAI_RT_TAPS / channelmod conf). Confirm in
   BOTH DU logs that per-client taps + path loss are applied ("[RT] injected N taps ...").
3. Verify the SINR split is real: a UE the twin puts on c0 should measure higher SNR/MCS on
   DU0 than DU1 (and vice-versa). Check this for >=1 UE before scaling.

## Measurement (now controlled)
- Per layout: baseline = UE on its strongest (ray-traced RSRP) cell; steered = rApp moves it
  to the other cell (run_traffic_steering -> association_changes gives which UEs move).
  Execute the move as a real F1 handover (scripted `ci trigger_f1_ho` is fine). Measure real
  iperf3 DL goodput in the baseline vs steered association -- now the UE experiences its
  actual RT channel to whichever cell serves it. Compare per-UE real gain to twin-predicted.
- Because both twin and real now use the SAME per-cell channels, the gap is a genuine
  fidelity measurement (not a channel mismatch).

## Sweep + success criterion
- Automate over >=8 layouts (seeds) like experiments/multignb_fidelity_gap.py; overwrite
  experiments/results/multignb_fidelity_gap.{csv,json} and regenerate paper/fig_multignb_gap.png.
- A MEANINGFUL result now shows twin and real gains CORRELATED (mostly same sign) with a
  much smaller std than the clean-channel run (165). Report the correlation (e.g. Pearson r
  or sign-agreement count) and mean+/-std of the gap.
- If they STILL decorrelate, the per-DU injection is probably not taking effect -- debug
  (are both DUs really applying per-client taps? is the path-loss split reproduced in the UE
  SNR?). Do NOT paper over a null result.

## Update the paper (only to what you actually measured)
- If controlled + meaningful: rewrite Sec. \ref{sec:multignb} to report the CONTROLLED
  multi-cell gap (twin vs real rApp gain, mean+/-std, correlation), and update the abstract,
  contributions, and conclusion to headline it. Keep the single-gNB link gap (53%/4.9pt) too.
- If still confounded/null: keep the honest "verified closed loop + per-cell grounding is
  hard in rfsim" framing; report the negative result plainly. Never headline a std>mean number.
- Keep 6 pages (IEEEtran). Compile: pdflatex main && bibtex main && pdflatex main && pdflatex main
  (0 errors, no undefined refs, no overfull boxes).

## Correctness + git hygiene (STRICT)
- Every number reproducible from experiments/results/* or OAI logs; verify per-DU injection
  in the logs before claiming a controlled measurement.
- GIT: commit ONLY specific files (e.g. `git add paper/main.tex paper/main.pdf experiments/...`).
  NEVER `git add -A` or `git add .` -- it will stage .venv/, output/, and
  experiments/results/scene/ (tens of thousands of files). The .gitignore already excludes
  those; keep it intact. Push to ants-submission; do not force-push or merge unrelated histories.
- If Option B fails or makes things worse, the paper can be restored from branch
  cursor/ants-submission-optiona-backup-f4bc.

## Definition of done
Per-UE ray-traced channels injected and VERIFIED on both DUs (logs show per-client taps +
path-loss; UE SNR/MCS differs between cells consistent with the twin); controlled twin-vs-real
multi-cell rApp gain measured over >=8 layouts (mean+/-std + correlation reported); paper
updated to match what was actually measured, 6 pages, compiling clean; committed to
ants-submission with specific adds and pushed.
```
