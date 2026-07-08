> **SUPERSEDED — historical artifact, do not follow.**
> This prompt was written for an earlier state of the repo and quotes numbers that have
> since been **retracted** (the multi-cell gap of 57±165 pts; the sub-band twin's rApp
> gains and its gain-vs-outage correlation). It also predates the seeded ray-tracing
> solver, so its numbers are not reproducible. Kept only as a record of how the work
> proceeded. For the current state see `README.md`, `experiments/README.md`, and
> `experiments/results/paper_stats.json`.

# Standalone prompt — finish the full OAI real-stack integration + update the paper

Copy everything in the block below into a fresh Cursor Agent session on your local
machine (after cloning the repo and checking out `ants-submission`). It is
self-contained: it gives the agent all the context, the exact steps, the results
to collect, and how to fold them into the paper.

> Prerequisite on your machine: a **stock Linux kernel with SCTP + TUN** and Docker
> + root/sudo. The whole point is that your local box can do what the cloud kernel
> could not. The agent will verify this first with `oai/check_host.sh`.

---

```
You are an expert 5G/O-RAN + LaTeX engineer. Work autonomously and test everything.

## Mission
Finish the FULL real-stack Standalone (SA) closed loop for this project's digital
twin, collect all results automatically, then update the IEEE ANTS paper so its
headline novelty is the MEASURED real-stack "fidelity gap" (the difference between
the rApp gain the analytical twin predicts and the gain the real OAI stack
delivers). A previous cloud agent did everything except the SA loop, because the
cloud kernel lacked SCTP and TUN. Your local machine has them, so you can finish it.

## First, read these for full context (do this before anything else)
- `AGENTS.md` — environment/run/test notes (twin is a CPU Python engine; use
  `export CUDA_VISIBLE_DEVICES=""` so Sionna RT runs on CPU without crashing).
- `oai/README_full_stack.md` — the step-by-step integration runbook (follow it).
- `paper/main.tex` + `paper/refs.bib` — the paper (double-blind IEEEtran, builds
  with pdflatex+bibtex, currently 6 pages). Title: "Closing the Fidelity Gap:
  Real-Stack-Grounded Link Abstraction for 5G Digital Twins".
- `experiments/` — the analytical results + harness (`sweep.py`, `fidelity_gap.py`,
  `results/*.csv`, `results/*.json`, `results/fig_*.png`).
- `oai/` scripts: `check_host.sh`, `setup_oai.sh`, `setup_cn5g.sh`,
  `run_multi_ue_rfsim.sh`, `setup_flexric.sh`, `iperf3_goodput.sh`,
  `cfr_to_oai_channel.py`, `interference_floor.py`, `rapp_closed_loop.py`,
  `collect_kpis.py`.

## What already exists (do NOT redo; build on it)
- The analytical twin: OpenStreetMap -> Sionna RT ray tracing -> per-UE/cell
  throughput, using an OAI-measured SINR->MCS link curve (`oai/sinr_throughput_table.json`).
- A proportional-fair traffic-steering rApp (per-cell CIO), evaluated over 24
  layouts (3 cities x 8 seeds). Headline analytical results (verified vs data;
  keep these): rApp median gain +9.5±11.3%, served cell-edge +22.4±24.8%, Jain
  +9.1%, peak load -0.75; mean UE outage 16.2%; throughput rises 1.7-1.8x as
  inter-cell load falls; link curve is 38% below Shannon at 10 dB.
- An ANALYTICAL fidelity-gap result already in the paper: swapping the OAI link
  curve for an idealized one changes the rApp's steering decisions in 42% of
  layouts and mis-estimates its per-deployment gain by a median 7.5 points.
- The OAI channel-injection path is verified: `[RT] injected N taps` runs the real
  OAI PHY over the ray-traced channel.

## What you must produce (the missing, strongest result)
The REAL fidelity gap: run the SAME rApp decision on the REAL OAI SA stack and
measure real per-UE goodput (iperf3) BEFORE vs AFTER steering; compare that real
gain to the twin-predicted gain for the same layout. Report it honestly whatever
it is — a measured gap (large OR small) is the paper's whole thesis and is novel.

## Phase 0 — host readiness (fail fast)
- Run `bash oai/check_host.sh`. It MUST print "READY". If SCTP or TUN is missing,
  fix the host (load modules / use a stock kernel) before spending 45 min building.

## Phase 1 — environments
- Twin: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`;
  `export CUDA_VISIBLE_DEVICES=""`; confirm with `python -m pytest -q`.
- Build OAI (gNB+UE) WITH control libs (needed for the loop):
  `bash oai/setup_oai.sh` then rebuild with telnet+E2:
  `cd ~/openairinterface5g/cmake_targets && CC=gcc CXX=g++ ./build_oai --gNB --nrUE --build-lib "telnetsrv e2" --ninja`.

## Phase 2 — 5G core
- `bash oai/setup_cn5g.sh`; verify EVERY NF is healthy:
  `sudo docker compose -f ~/oai-cn5g/docker-compose.yaml ps`. oai-amf and oai-upf
  must be healthy (they were the ones that failed on the cloud). Note the host
  bridge IP: `ip -4 addr show oai-cn5g` (typically 192.168.70.129). PLMN 001/01;
  subscribers 001010000000001..004 preloaded.

## Phase 3 — twin export + bridges
- `python3 -m dtrapp.runner.cli configs/example.yaml`  -> output/channel/{cfr.npy,network.json}
- `python3 oai/interference_floor.py output/channel`   -> interference_floor.conf
- `python3 oai/cfr_to_oai_channel.py output/channel --base-conf ~/openairinterface5g/ci-scripts/conf_files/gnb.sa.band78.106prb.rfsim.conf`

## Phase 4 — single-UE SA (validate the stack end-to-end)
- Align the SA gNB conf to the core: amf_ip_address=192.168.70.132, the
  GNB_IPV4_ADDRESS_FOR_NG_AMF/NGU = host bridge IP, PLMN mcc=001 mnc=01 len=2.
- Start gNB (SA rfsim) then one UE (imsi 001010000000001). SUCCESS =
  `NGSetupResponse` in the gNB log, UE gets `oaitun_ue1` an IP, and
  `ip netns exec ue1 ping -c3 192.168.70.135` works.
- If it fails, DEBUG methodically: `NGSetupFailure` => PLMN or amf_ip mismatch;
  `--sa unknown option` => drop the flag (SA is default); no `oaitun_ue1` =>
  TUN/UPF problem (re-check `oai/check_host.sh`). Use the debug subagent if stuck.

## Phase 5 — multi-UE + per-UE ray-traced channel + interference
- Ensure the SA gNB conf `@include`s interference_floor.conf.
- `sudo NUE=3 GNB_CONF=/abs/gnb_sa.conf UE_CONF=/abs/ue.conf OAI_RT_TAPS=$PWD/output/channel/oai_rt_taps.txt bash oai/run_multi_ue_rfsim.sh 60`
- Confirm all 3 UEs register and get IPs.

## Phase 6 — FlexRIC + close the loop + MEASURE THE FIDELITY GAP (automate this)
Write a script `experiments/real_fidelity_gap.py` (or a bash driver) that, for a
few layouts/seeds, automatically:
  1. brings up gNB (E2 agent) + N UEs on their ray-traced channels + interference,
  2. starts FlexRIC + the KPM xApp (`bash oai/setup_flexric.sh`) and logs per-UE KPMs,
  3. measures BASELINE per-UE goodput: `sudo NUE=3 SERVER_IP=192.168.70.135 bash oai/iperf3_goodput.sh`,
  4. applies the rApp decision: `python3 oai/rapp_closed_loop.py output/channel --pci-map c0=0,c1=1,c2=2 --apply --telnet-port 9090`,
  5. measures STEERED per-UE goodput again,
  6. computes real gain = (steered - baseline)/baseline, and the FIDELITY GAP =
     twin-predicted gain (from `experiments/`) - real gain,
  7. writes results to `experiments/results/real_fidelity_gap.{csv,json}` and a
     figure `paper/fig_real_fidelity_gap.png` (twin-predicted vs real per-UE gain,
     y=x line; annotate the gap).
Run it and collect the numbers. Repeat across enough layouts to report a mean±std.

## Phase 7 — update the paper (make novelty proper)
- Add a Results subsection "The real fidelity gap" presenting the measured
  twin-predicted-vs-real gain, with `fig_real_fidelity_gap.png`. Lead the abstract,
  contribution list, and conclusion with this REAL result (it supersedes the
  analytical-only fidelity gap as the headline; keep the analytical one as the
  motivating/agreeing evidence).
- Keep it to 6 pages (IEEEtran conference). Trim redundancy if needed.
- Compile: `cd paper && pdflatex main && bibtex main && pdflatex main && pdflatex main`.
  Must be 0 errors, no undefined refs, no overfull boxes.

## Correctness rules (STRICT — a reviewer already caught fabricated numbers here)
- EVERY number in the paper must be reproducible from committed data/logs
  (`experiments/results/*` or OAI logs). Never invent a statistic or R^2.
- If the real fidelity gap is small or the loop is partially working, SAY SO
  plainly — an honest measured gap is the contribution; do not oversell.
- Re-verify existing paper numbers still match `experiments/results/*` after edits.

## Evidence + git
- Save logs/figures under `experiments/results/` and reference them.
- Keep OAI processes/core running when you finish so I can inspect.
- Commit in logical chunks and push to `ants-submission`. Do not force-push.
  Create/update a PR at the end. Two refs.bib entries (OpenTwin, OAI+FlexRIC
  handover) have placeholder authors — fill in real citations.

## Definition of done
`oai/check_host.sh` READY; core all-healthy; multi-UE SA registered with real
iperf3 goodput; FlexRIC streaming KPMs; rApp applied via telnet; the real
fidelity gap measured and written to `experiments/results/real_fidelity_gap.*`;
the paper updated with it as the headline novelty, compiling clean to 6 pages;
all committed and pushed.
```
