#!/usr/bin/env python3
"""Drive a live 2-cell OAI SA stack (CU + 2 F1 DUs + 1 UE) with a reversal design.

Why this module exists
----------------------
The first multi-cell driver measured the UE's goodput once *before* a handover
(always on DU0) and once *after* it (always on DU1), then relabelled those two
numbers by cell identity. Measurement order and cell identity were therefore
perfectly confounded: any post-handover transient, DU warm-up or CPU-contention
effect was attributed to the *cell*. Since the executed handover is always
DU0 -> DU1 (``find_target_du`` picks the next DU), the sign of the resulting
"real gain" is a pure function of the direction the rApp happened to choose.

This module removes that confound in three ways:

1. **Reversal (A/B/A/B) design, probed at TCP's plateau.** ``ci trigger_f1_ho``
   toggles between the two DUs, so we chain handovers and measure repeatedly. The
   first (pre-handover) measurement is discarded and the remaining ones are
   balanced across cells at equal mean sequence position, so a monotone drift
   cancels to first order. The probe itself matters more than the design: see the
   note above ``measure_goodput``.
2. **Per-cell ray-traced channels.** The UE is the rfsim *server*, so the
   channel of the n-th DU to connect is ``rfsimu_channel_ue{n-1}`` and
   ``rxAddInput`` sums all DUs' waveforms into the UE's receive buffer. Writing
   one taps block per DU therefore gives each cell its own ray-traced link gain,
   and the non-serving cell becomes real co-channel interference.
3. **Co-channel DUs.** The stock ``pci1`` DU conf sits on a different carrier
   (3649.44 vs 3450.72 MHz) with a different SSB burst position. rfsim has no RF
   front end, so both DUs' basebands overlap anyway. ``oai/conf/*.pci1.cochannel.conf``
   makes DU1 identical to DU0 except PCI/cell-id, matching the twin's two co-channel
   sectors. (With a correct probe the null control finds no difference between the two
   DU configurations, so this is for physical fidelity, not to fix the bias.)

Nothing here interprets results; see ``experiments/multignb_null_control.py`` and
``experiments/multignb_fidelity_gap.py``.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OAI = Path.home() / "openairinterface5g"
BUILD = OAI / "cmake_targets/ran_build/build"
CONF_DIR = OAI / "targets/PROJECTS/GENERIC-NR-5GC/CONF"

CU_CONF = CONF_DIR / "gnb-cu.sa.f1.conf"
DU0_CONF = CONF_DIR / "gnb-du.sa.band78.106prb.rfsim.pci0.conf"
DU1_CONF_DIFFFREQ = CONF_DIR / "gnb-du.sa.band78.106prb.rfsim.pci1.conf"
DU1_CONF_COCHANNEL = ROOT / "oai/conf/gnb-du.sa.band78.106prb.rfsim.pci1.cochannel.conf"

RUN = ROOT / "oai_run"
SERVER_IP = "192.168.70.135"       # oai-ext-dn (iperf3 server)
TELNET_PORT = 9090
DL_FREQ = "3450720000"             # DU0's carrier; DU1 shares it in co-channel mode
IMSI = "001010000000001"

# DU start order defines the rfsim connection order, hence the channel model
# each DU gets on the UE (server) side. Do not reorder without updating this.
DU_ORDER_PCI = (0, 1)


def sh(cmd: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=timeout)


def kill_all() -> None:
    sh("sudo pkill -x nr-uesoftmodem; sudo pkill -x nr-softmodem; true")
    for _ in range(20):                       # let the GTP/SCTP sockets actually close
        time.sleep(0.5)
        if not sh("pgrep -x nr-softmodem; pgrep -x nr-uesoftmodem").stdout.strip():
            break
    else:
        sh("sudo pkill -9 -x nr-uesoftmodem; sudo pkill -9 -x nr-softmodem; true")
        time.sleep(2)
    time.sleep(2)


def ensure_iperf_server() -> None:
    sh("sudo docker exec oai-ext-dn pkill iperf3 2>/dev/null; true")
    sh("sudo docker exec oai-ext-dn iperf3 -s -D")


def _read(p: Path) -> str:
    return p.read_text(errors="ignore") if p.exists() else ""


def wait_log(log: Path, pattern: str, timeout: int, offset: int = 0) -> re.Match | None:
    pat = re.compile(pattern)
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = pat.search(_read(log)[offset:])
        if m:
            return m
        time.sleep(0.5)
    return None


# Why TCP, and why at a plateau
# -----------------------------
# A saturating UDP source looks like the obvious capacity probe, and it is what an earlier
# version of this harness used. It does not work here. In reverse mode iperf3's
# ``end.sum.bits_per_second`` reports the *sending* rate: with the gNB pinned to
# ``dl_max_mcs = 4`` (a ~10 Mbps MAC) an 8 Mbps offer reports exactly 8.00 Mbps and a
# 20 Mbps offer exactly 20.00 Mbps, both with ~0% loss. Those numbers are the source rate,
# not the delivered rate, and any "gap" computed from them is fiction. Raising the offer
# until loss appears is not an option either: iperf3's control connection rides the same
# PDU session, so a flood starves it and the run hangs.
#
# TCP self-clocks: it cannot exceed the channel. Its cost is slow start -- it needs tens of
# seconds to reach a plateau, and the *original* harness sampled it 3 s after a handover
# with a 6 s flow, so it read the congestion window rather than the channel. Measured on
# two physically identical cells, that instrument reports a -21.0 +/- 1.4% cell effect where
# the truth is 0; probing at the plateau instead brings it to -2.4 +/- 2.9%. See
# experiments/multignb_null_control.py. The plateau is min(channel capacity,
# transport/compute ceiling); on this host the ceiling is real and is itself part of the
# twin-vs-stack gap, so we report it rather than hide it.
TCP_SETTLE_S = 20
TCP_DUR_S = 20


def measure_goodput(ip: str, dur: int, protocol: str = "tcp") -> dict:
    """Delivered DL goodput (Mbps) from an iperf3 flow.

    ``tcp`` (default) reports ``end.sum_received``, the receiver's own byte count.
    ``tcp6`` is the original instrument (6 s, no settle), kept for the null control.
    """
    try:
        r = sh(f"iperf3 -c {SERVER_IP} -B {ip} -t {dur} -R -J", timeout=dur + 90)
        gp = json.loads(r.stdout)["end"]["sum_received"]["bits_per_second"] / 1e6
    except Exception:
        gp = None
    return {"goodput_mbps": gp}


_DLSCH = re.compile(r"MCS \(\d+\) (\d+) CCE fail \d+, goodput ([\d.]+) Mbps")


def dl_mcs_goodput(du_log: Path, offset: int = 0) -> tuple[int | None, float | None]:
    """Peak DL MCS and peak MAC DL goodput on a DU over a log window.

    OAI's DL link adaptation converges to the channel, so the peak MCS on lines
    that carry real traffic is the operating point. ``offset`` restricts the
    window to the current measurement.
    """
    mcss, gps = [], []
    for m in _DLSCH.finditer(_read(du_log)[offset:]):
        mcs, gp = int(m.group(1)), float(m.group(2))
        if gp > 0.5:                       # ignore idle / ramp-up lines
            mcss.append(mcs)
            gps.append(gp)
    return (max(mcss) if mcss else None, max(gps) if gps else None)


@dataclass
class Stack:
    """A running CU + DU0 + DU1 + UE stack. ``pci`` tracks the serving cell."""

    tag: str
    ue_conf: Path
    taps: Path | None = None
    cochannel: bool = True
    ip: str = ""
    pci: int = 0
    cu_log: Path = field(init=False)
    du_logs: dict[int, Path] = field(init=False)
    ue_log: Path = field(init=False)

    def __post_init__(self) -> None:
        RUN.mkdir(parents=True, exist_ok=True)
        # The softmodems are launched from BUILD, so every path handed to them
        # (conf, taps) must be absolute.
        self.ue_conf = Path(self.ue_conf).resolve()
        if self.taps is not None:
            self.taps = Path(self.taps).resolve()
        self.cu_log = RUN / f"cu_{self.tag}.log"
        self.du_logs = {0: RUN / f"du0_{self.tag}.log", 1: RUN / f"du1_{self.tag}.log"}
        self.ue_log = RUN / f"ue_{self.tag}.log"

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> str:
        for p in (self.cu_log, *self.du_logs.values(), self.ue_log):
            p.unlink(missing_ok=True)
        kill_all()

        subprocess.Popen(
            f'cd "{BUILD}" && sudo nohup ./nr-softmodem -O "{CU_CONF}" '
            f'--telnetsrv --telnetsrv.shrmod ci > "{self.cu_log}" 2>&1 &', shell=True)
        if wait_log(self.cu_log, r"Received NGSetupResponse", 60) is None:
            raise RuntimeError("CU failed NGSetup")

        # DU0 first: it becomes rfsim connection 0 -> channel model rfsimu_channel_ue0.
        self._start_du(0, DU0_CONF)

        # UE is the rfsim SERVER; OAI_RT_TAPS must survive sudo's env reset.
        env = f'OAI_RT_TAPS="{self.taps}" ' if self.taps else ""
        subprocess.Popen(
            f'cd "{BUILD}" && sudo env {env}nohup ./nr-uesoftmodem -C {DL_FREQ} -r 106 '
            f'--numerology 1 --ssb 516 --rfsim -O "{self.ue_conf}" '
            f'--rfsimulator.[0].serveraddr server --uicc0.imsi {IMSI} '
            f'> "{self.ue_log}" 2>&1 &', shell=True)
        m = wait_log(self.ue_log, r"oaitun_ue1 successfully configured, IPv4 ([\d.]+)", 120)
        if m is None:
            raise RuntimeError("UE attach failed")
        self.ip = m.group(1)
        sync = re.findall(r"Initial sync successful, PCI: (\d+)", _read(self.ue_log))
        self.pci = int(sync[-1]) if sync else 0

        # DU1 second -> rfsim connection 1 -> rfsimu_channel_ue1.
        du1 = DU1_CONF_COCHANNEL if self.cochannel else DU1_CONF_DIFFFREQ
        self._start_du(1, du1)
        time.sleep(6)
        return self.ip

    def _start_du(self, idx: int, conf: Path, attempts: int = 3) -> None:
        """Start a DU and wait for its F1 Setup Response.

        The DU binds a GTP-U socket the moment it starts; if a previous run's DU
        has not fully released it the DU asserts out ("cannot create DU F1-U GTP
        module") and the UE then silently fails to sync. Verify and retry rather
        than discover it three minutes later as a missing measurement.
        """
        log = self.du_logs[idx]
        for a in range(attempts):
            log.unlink(missing_ok=True)
            subprocess.Popen(
                f'cd "{BUILD}" && sudo nohup ./nr-softmodem --rfsim -O "{conf}" '
                f'--rfsimulator.[0].serveraddr 127.0.0.1 > "{log}" 2>&1 &', shell=True)
            if wait_log(log, r"received F1 Setup Response from CU", 40) is not None:
                return
            sh(f"sudo pkill -f '{conf.name}'")
            time.sleep(5 * (a + 1))
        raise RuntimeError(f"DU{idx} failed F1 setup after {attempts} attempts ({log})")

    def stop(self) -> None:
        kill_all()

    # -- verification ------------------------------------------------------
    def injected_models(self) -> list[tuple[str, float]]:
        """(model_name, path_loss_dB) pairs the OAI patch reports on the UE side."""
        pat = re.compile(r"\[RT\] injected \d+ taps into (\S+) \(path_loss_dB=(-?[\d.]+)")
        return [(m.group(1), float(m.group(2))) for m in pat.finditer(_read(self.ue_log))]

    def activated_models(self) -> list[str]:
        return re.findall(r"Random channel (\S+) in rfsimulator activated", _read(self.ue_log))

    def resyncs_after_attach(self) -> int:
        """Downlink re-sync attempts after the PDU session came up.

        A handover legitimately causes one ("Initial sync successful, PCI: x" on the
        target). A run that keeps re-syncing has lost the downlink, and any goodput
        number from it is meaningless.
        """
        txt = _read(self.ue_log)
        i = txt.find("oaitun_ue1 successfully configured")
        return len(re.findall(r"synch Failed", txt[i:])) if i >= 0 else 0

    # -- control -----------------------------------------------------------
    def handover(self, timeout: int = 40) -> int | None:
        """Trigger an F1 handover to the *other* DU. Returns the new PCI, else None."""
        off = len(_read(self.cu_log))
        sh(f'echo "ci trigger_f1_ho" | nc -N 127.0.0.1 {TELNET_PORT}')
        if wait_log(self.cu_log, r"handover for UE .* complete", timeout, offset=off) is None:
            return None
        m = re.search(r"Handover triggered for UE .*?/PCI (\d+)", _read(self.cu_log)[off:])
        if m is None:
            return None
        self.pci = int(m.group(1))
        return self.pci

    # -- measurement -------------------------------------------------------
    def measure(self, dur: int = TCP_DUR_S, settle: int = TCP_SETTLE_S) -> dict:
        """One DL measurement on the current serving cell.

        ``settle`` lets the target DU's downlink link adaptation and TCP's congestion
        window converge after a handover (both restart on every one).
        """
        time.sleep(settle)
        du_log = self.du_logs[self.pci]
        off = len(_read(du_log))
        r = measure_goodput(self.ip, dur)
        mcs, mac_gp = dl_mcs_goodput(du_log, off)
        return {"pci": self.pci, **r, "dl_mcs": mcs, "mac_goodput_mbps": mac_gp}


def reversal_sequence(stack: Stack, n: int = 6, dur: int = TCP_DUR_S,
                      settle: int = TCP_SETTLE_S) -> list[dict]:
    """Measure ``n`` times, handing over between each. Discard nothing here.

    Position 1 is the only pre-handover measurement; callers drop it. With n=6 the
    remaining positions 2..6 give cell A {3,5} and cell B {2,4,6}: equal mean
    sequence position (4.0), so a linear drift in sequence position cancels.
    """
    rows: list[dict] = []
    for i in range(n):
        if i > 0 and stack.handover() is None:
            rows.append({"pos": i + 1, "pci": None, "goodput_mbps": None,
                         "dl_mcs": None, "mac_goodput_mbps": None, "ho_ok": 0})
            break
        r = stack.measure(dur=dur, settle=settle)
        r["pos"] = i + 1
        r["ho_ok"] = 1 if i > 0 else 0
        rows.append(r)
    return rows


def balanced_cell_means(rows: list[dict]) -> dict:
    """Per-cell goodput from a reversal sequence, discarding the pre-handover point."""
    import numpy as np

    post = [r for r in rows if r["pos"] > 1 and r["goodput_mbps"] is not None]
    out: dict = {}
    for pci in (0, 1):
        vals = [r["goodput_mbps"] for r in post if r["pci"] == pci]
        pos = [r["pos"] for r in post if r["pci"] == pci]
        mcs = [r["dl_mcs"] for r in post if r["pci"] == pci and r["dl_mcs"] is not None]
        out[f"g_pci{pci}_mbps"] = float(np.mean(vals)) if vals else None
        out[f"n_pci{pci}"] = len(vals)
        out[f"meanpos_pci{pci}"] = float(np.mean(pos)) if pos else None
        out[f"mcs_pci{pci}"] = float(np.mean(mcs)) if mcs else None
    return out
