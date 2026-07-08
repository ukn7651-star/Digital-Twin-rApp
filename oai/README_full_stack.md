# Full integration runbook — twin → real OAI SA closed loop

End-to-end steps to turn the analytical twin into a **multi-UE, real-stack,
closed-loop** system: OAI Standalone core + gNB + multiple UEs, each UE on its
own ray-traced channel and inter-cell interference noise floor, with the
traffic-steering rApp driving handovers and the **fidelity gap** measured as
twin-predicted vs. real-stack goodput.

> **Read this first — host requirement.** The full loop needs a Linux host whose
> **kernel has SCTP** (for the gNB↔AMF NGAP/N2 link) **and the TUN driver** (for
> the UPF N6 + UE data plane). A locked-down cloud kernel (no `/lib/modules`,
> no `modprobe`) **cannot** run it — the AMF crashes and the UPF fails on
> `/dev/net/tun`. Use a stock Ubuntu VM (GCP/AWS/Azure default images) or bare
> metal. Run `bash oai/check_host.sh` and only proceed if it says READY.

## Verified status (what has actually been run)

| Step | Verified on cloud CPU here? |
|---|---|
| Twin: ray-trace + export CFR (`dtrapp.runner.cli`) | ✅ yes |
| Twin bridges (interference floor, CFR→taps, rApp decision) | ✅ yes (unit-tested + run) |
| Build OAI gNB+UE from source (`setup_oai.sh`) | ✅ yes |
| Real OAI PHY over rfsim (phy-test) | ✅ yes (MCS 9, 10% BLER) |
| Ray-traced channel **injection** into the live link | ✅ yes (`[RT] injected 4 taps … channel_length=49`) |
| Pull 5G core images (`setup_cn5g.sh`) | ✅ yes |
| 5G core NFs healthy (AMF/UPF) | ❌ needs SCTP+TUN kernel |
| Multi-UE SA registration + iperf3 goodput | ❌ needs SCTP+TUN kernel |
| FlexRIC KPM + rApp handover closed loop | ❌ needs SCTP+TUN kernel |

Everything up to and including channel injection runs on any CPU host; the last
three rows are what a proper-kernel host unlocks.

---

## Step 0 — clone + host check
```bash
git clone <repo-url> && cd <repo>
git checkout ants-submission
bash oai/check_host.sh          # must print "READY" for the full loop
```

## Step 1 — Python twin environment
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # sionna-rt, sionna, torch (CPU ok)
export CUDA_VISIBLE_DEVICES=""            # force CPU (avoids the Sionna RT GPU crash)
python -m pytest -q                       # sanity: twin tests pass (Sionna auto-skips if absent)
```

## Step 2 — build OAI (gNB + UE), ~30–45 min
```bash
bash oai/setup_oai.sh                     # clones OAI, applies the RT-injection patch, builds
# For the closed loop you also need telnet (handover) + E2 (FlexRIC):
#   cd ~/openairinterface5g/cmake_targets
#   CC=gcc CXX=g++ ./build_oai --gNB --nrUE --build-lib "telnetsrv e2" --ninja
```
Verify: `ls ~/openairinterface5g/cmake_targets/ran_build/build/{nr-softmodem,nr-uesoftmodem}`

## Step 3 — bring up the 5G core (Docker)
```bash
bash oai/setup_cn5g.sh                     # fetches compose+config set, pulls images, starts core
sudo docker compose -f ~/oai-cn5g/docker-compose.yaml ps    # oai-amf & oai-upf must be 'healthy'
```
Note the host's bridge IP: `ip -4 addr show oai-cn5g` (e.g. `192.168.70.129`). PLMN is
**001/01**; subscribers **001010000000001..004** are preloaded.

## Step 4 — export the ray-traced channel from the twin
```bash
python3 -m dtrapp.runner.cli configs/example.yaml     # -> output/channel/{cfr.npy,network.json}
python3 oai/interference_floor.py output/channel      # -> interference_floor.conf (per-UE noise floor)
python3 oai/cfr_to_oai_channel.py output/channel \
        --base-conf ~/openairinterface5g/ci-scripts/conf_files/gnb.sa.band78.106prb.rfsim.conf
#   -> output/channel/{oai_rt_taps.txt, gnb_rtchan.conf, ue_rtchan.conf}
```

## Step 5 — single-UE SA attach (validate the stack)
Align the SA gNB conf to the core, then launch gNB + one UE:
```bash
GNB=~/openairinterface5g/ci-scripts/conf_files/gnb.sa.band78.106prb.rfsim.conf
sed -i 's/192.168.70.132/192.168.70.132/;                    # amf_ip_address (already .132)
        s/ipv4 *= *"[0-9.]*"; *#GNB_NGU/ipv4 = "192.168.70.129";/' "$GNB"   # host bridge IP
# (edit amf_ip_address -> 192.168.70.132 and GNB_IPV4_ADDRESS_FOR_NG_AMF/NGU -> host bridge IP,
#  and PLMN mcc=001 mnc=01 length=2; these match the core.)
cd ~/openairinterface5g/cmake_targets/ran_build/build
sudo ./nr-softmodem -O "$GNB" --rfsim --rfsimulator.serveraddr server &   # SA is default; omit --sa if rejected
sudo ./nr-uesoftmodem --rfsim -r 106 --numerology 1 --band 78 -C 3619200000 \
     --rfsimulator.serveraddr 127.0.0.1 --uicc0.imsi 001010000000001 &
```
Success = gNB log shows `NGSetupResponse`, UE gets `oaitun_ue1` an IP, and:
```bash
ip netns exec ue1 ping -c3 192.168.70.135      # data network reachable
```
Gotchas: `--sa unknown option` → drop it (SA is default on recent builds);
`NGSetupFailure` → PLMN or `amf_ip_address` mismatch; no `oaitun_ue1` → TUN/UPF issue.

## Step 6 — channel injection + multi-UE + interference floor
```bash
# gNB SA conf must @include the interference floor; connection order maps clients
# to rfsimu_channel_ue0, ue1, ... :
echo '@include "'$PWD'/interference_floor.conf"' >> "$GNB"
sudo NUE=3 GNB_CONF="$GNB" UE_CONF=<ue.conf> \
     OAI_RT_TAPS=$PWD/output/channel/oai_rt_taps.txt \
     bash oai/run_multi_ue_rfsim.sh 60
```

## Step 7 — FlexRIC + close the loop + measure the fidelity gap
```bash
bash oai/setup_flexric.sh                        # build RIC + KPM xApp (needs the E2-enabled gNB)
./build/examples/ric/nearRT-RIC &                # start the RIC (in ~/flexric)
# start gNB (with e2_agent block) + UEs as in Step 6, then the KPM xApp:
./build/examples/xApp/c/monitor/xapp_kpm_moni    # streams per-UE MCS/BLER/throughput

# baseline goodput, then apply the rApp's steering decision, then re-measure:
sudo NUE=3 SERVER_IP=192.168.70.135 bash oai/iperf3_goodput.sh          # -> baseline per-UE goodput
python3 oai/rapp_closed_loop.py output/channel --pci-map c0=0,c1=1,c2=2 \
        --apply --telnet-port 9090                                       # execute handovers
sudo NUE=3 SERVER_IP=192.168.70.135 bash oai/iperf3_goodput.sh          # -> steered per-UE goodput
```
**Fidelity gap** = (rApp gain the twin predicts, from `experiments/`) − (rApp gain
the real stack delivers, from the two iperf3 runs). That single number is the
headline the full loop produces.

---

## Gotchas found while validating on cloud CPU
- **Docker on an overlay root fs**: set `{"storage-driver":"vfs"}` in
  `/etc/docker/daemon.json` (handled by `setup_cn5g.sh`).
- **CN5G config files**: the compose bind-mounts `conf/config.yaml`, the
  subscriber DB, and a healthcheck; fetch them *before* `up` or Docker creates
  them as root-owned dirs (handled by `setup_cn5g.sh`).
- **phy-test must run as non-root** (SCHED_FIFO); **multi-UE SA must run as root**
  (network namespaces).
- **`run_phytest.sh` cd's into the build dir** → pass `CONF`/`OAI_RT_TAPS`/`UE_CONF`
  as **absolute** paths.
- **Sionna RT on a GPU host** may crash in `path_solvers` → `export CUDA_VISIBLE_DEVICES=""`.
