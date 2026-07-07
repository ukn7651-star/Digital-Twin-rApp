#!/usr/bin/env bash
# Measure per-UE downlink goodput with iperf3 over each UE's tunnel interface.
#
# =============================================================================
# NOT YET INTEGRATION-TESTED END-TO-END. Requires a full Linux host with root, a
# running SA stack (core + gNB + UEs from oai/run_multi_ue_rfsim.sh), the UE
# `oaitun_ue1` interfaces up, and CAP_NET_ADMIN. A minimal host may provide none
# of these. phy-test reports 0 goodput by design (no user traffic), which is why
# real goodput needs this SA + tunnel path.
# =============================================================================
#
# Model: iperf3 server on the core-network data side, client bound to each UE's
# tunnel interface; downlink = server -> UE (use -R on the client).
#
# Usage:
#   sudo NUE=3 SERVER_IP=192.168.70.135 DURATION=15 bash oai/iperf3_goodput.sh [out.csv]
set -euo pipefail

NUE="${NUE:-3}"
SERVER_IP="${SERVER_IP:?set SERVER_IP to the iperf3 server (CN data network) address}"
DURATION="${DURATION:-15}"
OUT="${1:-oai_run_multi/iperf3_goodput.csv}"

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
command -v iperf3 >/dev/null 2>&1 || { echo "iperf3 not found (apt-get install iperf3)"; exit 1; }
command -v ip >/dev/null 2>&1 || { echo "'ip' not found (needs a full host)"; exit 1; }

mkdir -p "$(dirname "$OUT")"
echo "ue_index,tun_if,dl_goodput_mbps" > "$OUT"

for i in $(seq 1 "$NUE"); do
  ns="ue$i"; tun="oaitun_ue1"   # each UE namespace exposes its own oaitun_ue1
  echo "[UE $i] iperf3 downlink for ${DURATION}s ..."
  # -R: reverse (server sends -> downlink to UE). JSON output parsed for goodput.
  mbps="$(ip netns exec "$ns" iperf3 -c "$SERVER_IP" -t "$DURATION" -R -J 2>/dev/null \
          | grep -oE '"bits_per_second":[ ]*[0-9.]+' | tail -1 \
          | grep -oE '[0-9.]+' | awk '{printf "%.2f", $1/1e6}')"
  echo "  UE $i: ${mbps:-NA} Mbps"
  echo "$i,$tun,${mbps:-NA}" >> "$OUT"
done

echo "wrote $OUT"
