#!/usr/bin/env bash
# Pre-flight check: can THIS host run the FULL OAI SA closed loop?
#
# The full loop (5G core + multi-UE registration + user-plane iperf3 goodput +
# FlexRIC) needs two things the analytical twin does NOT: kernel SCTP (for the
# gNB<->AMF NGAP/N2 link) and the TUN driver (for the UPF N6 + UE data plane).
# Locked-down cloud kernels (no /lib/modules, no modprobe) usually lack both.
#
# Usage:  bash oai/check_host.sh
set -u
fail=0
say(){ printf "  %-26s %s\n" "$1" "$2"; }

echo "OAI full-stack host readiness:"

# root / sudo
if [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null; then say "root/sudo:" "OK"
else say "root/sudo:" "WARN - some steps (core, netns) need root"; fi

# SCTP (NGAP / N2) -- hard requirement
if python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM, 132)" 2>/dev/null; then
  say "SCTP (gNB<->AMF N2):" "OK"
else
  sudo modprobe sctp 2>/dev/null && python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM, 132)" 2>/dev/null \
    && say "SCTP (gNB<->AMF N2):" "OK (loaded module)" \
    || { say "SCTP (gNB<->AMF N2):" "MISSING - NGAP will fail (no SA registration)"; fail=1; }
fi

# TUN (user plane) -- hard requirement. Authoritative test: actually create a
# tun interface (a bare /dev/net/tun node can exist while the driver is absent).
if command -v ip >/dev/null 2>&1 && sudo ip tuntap add mode tun name _chktun0 2>/dev/null; then
  sudo ip tuntap del mode tun name _chktun0 2>/dev/null
  say "TUN (user plane):" "OK"
elif sudo modprobe tun 2>/dev/null && sudo ip tuntap add mode tun name _chktun0 2>/dev/null; then
  sudo ip tuntap del mode tun name _chktun0 2>/dev/null
  say "TUN (user plane):" "OK (loaded module)"
else
  say "TUN (user plane):" "MISSING - UPF/UE data plane + iperf3 will fail"; fail=1
fi

# Docker (5G core)
if command -v docker >/dev/null 2>&1 && (docker info >/dev/null 2>&1 || sudo docker info >/dev/null 2>&1); then
  say "Docker + daemon:" "OK"
else say "Docker + daemon:" "MISSING - needed for the 5G core (install: get.docker.com)"; fi

# iproute2 (multi-UE netns)
command -v ip >/dev/null 2>&1 && say "iproute2 (ip):" "OK" || say "iproute2 (ip):" "MISSING - sudo apt install iproute2"

# kernel modules available at all?
[ -d "/lib/modules/$(uname -r)" ] && say "kernel modules dir:" "present" \
  || say "kernel modules dir:" "ABSENT (/lib/modules/$(uname -r)) - cannot load modules"

echo
if [ "$fail" -ne 0 ]; then
  echo "==> NOT READY for the full SA loop: this kernel lacks SCTP and/or TUN and"
  echo "    they cannot be loaded here. Use a host with a stock Linux kernel"
  echo "    (standard Ubuntu VM / bare metal), not a locked-down cloud kernel."
  echo "    The analytical twin and phy-test channel injection still work anywhere."
  exit 1
fi
echo "==> READY: this host can run the full OAI SA closed loop."
