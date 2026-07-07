#!/usr/bin/env python3
"""Traffic-steering rApp -> OAI closed loop (decision here, execution on a host).

Runs the load-balancing rApp on the twin (reusing ``dtrapp.rapp``), converts the
steering decision into concrete per-UE handovers, and emits the OAI telnet
commands that execute them on a running multi-cell OAI stack. With ``--apply`` it
sends the commands to the gNB telnet server; otherwise it prints them (dry run).

Decision logic (twin side) is pure Python and unit-tested. The ``--apply`` path
requires a running multi-cell OAI + telnet server built with ``--build-lib
telnetsrv`` and a cell_id->PCI map; it is exercised on a full host (see
oai/README_full_stack.md).

Usage:
    python3 oai/rapp_closed_loop.py [channel_dir] [--config configs/example.yaml]
        [--pci-map c0=0,c1=1,...] [--telnet-host 127.0.0.1] [--telnet-port 9090]
        [--apply]
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtrapp.rapp import association_changes, run_traffic_steering
from dtrapp.runner.rapp_cli import _load_config, load_network


def _parse_pci_map(spec: str | None) -> dict:
    if not spec:
        return {}
    out = {}
    for pair in spec.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = int(v)
    return out


def handover_commands(handovers: list[dict], pci_map: dict) -> list[str]:
    """OAI telnet N2-handover triggers for each per-UE cell change.

    Format follows the OAI handover tutorial: ``ci trigger_n2_ho <target_pci>
    <ue_id>`` issued at the source gNB. UE ids here are twin labels; on the host
    they map to the connected UE index. cell_id->PCI comes from ``pci_map``.
    """
    cmds = []
    for i, ho in enumerate(handovers):
        target = pci_map.get(ho["to_cell"], ho["to_cell"])
        cmds.append(f"ci trigger_n2_ho {target} {i}   # {ho['ue_id']}: "
                    f"{ho['from_cell']} -> {ho['to_cell']}")
    return cmds


def _send_telnet(host: str, port: int, cmd: str) -> None:  # pragma: no cover - host only
    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall((cmd + "\n").encode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel_dir", nargs="?", default="output/channel")
    ap.add_argument("--config", default="configs/example.yaml")
    ap.add_argument("--pci-map", default=None, help="cell_id=PCI,...")
    ap.add_argument("--telnet-host", default="127.0.0.1")
    ap.add_argument("--telnet-port", type=int, default=9090)
    ap.add_argument("--apply", action="store_true",
                    help="send commands to the gNB telnet server (needs a running host stack)")
    args = ap.parse_args()

    d = Path(args.channel_dir)
    cfr = np.load(d / "cfr.npy")
    network = load_network(d / "network.json")
    config = _load_config(args.config)

    out = run_traffic_steering(network, cfr, config)
    hos = association_changes(out.baseline, out.steered)
    cmds = handover_commands(hos, _parse_pci_map(args.pci_map))

    g = out.gains_pct()
    print(f"rApp decision: {len(hos)} handover(s); twin predicts "
          f"edge {g['edge_mbps']:+.1f}%, sum {g['sum_mbps']:+.1f}%, "
          f"fairness {g['jain']:+.1f}%, peak load {g['max_load_delta']:+.0f}")
    for c in cmds:
        print(f"  {c}")

    if args.apply:  # pragma: no cover - requires a running OAI host stack
        for c in cmds:
            cmd = c.split("#")[0].strip()
            try:
                _send_telnet(args.telnet_host, args.telnet_port, cmd)
                print(f"  [applied] {cmd}")
            except OSError as e:
                print(f"  [FAILED] {cmd}  ({e})")
                return 1
    else:
        print("dry run (no --apply): commands above are not sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
