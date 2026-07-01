#!/usr/bin/env bash
# Run OAI gNB + UE in phy-test + rfsimulator mode (no radio hardware).
#
# IMPORTANT: run as a NON-ROOT user (no sudo). Under sudo, OAI tries real-time
# scheduling (SCHED_FIFO), which sandboxed containers forbid -> it crashes.
# As a normal user it skips real-time scheduling and runs fine.
#
# Usage:  bash oai/run_phytest.sh [duration_seconds]   (default: 30)
# Env:    OAI_DIR (default $HOME/openairinterface5g), OUT_DIR (default ./oai_run)
set -uo pipefail

OAI_DIR="${OAI_DIR:-$HOME/openairinterface5g}"
DURATION="${1:-30}"
OUT_DIR="${OUT_DIR:-$(pwd)/oai_run}"
BUILD="$OAI_DIR/cmake_targets/ran_build/build"
# Default gNB config; override with CONF=... (e.g. the RT-channel conf produced by
# cfr_to_oai_channel.py) to run OAI over the ray-traced channel.
CONF="${CONF:-$OAI_DIR/ci-scripts/conf_files/gnb.band78.106prb.rfsim.phytest-dora.conf}"

if [ ! -x "$BUILD/nr-softmodem" ]; then
  echo "nr-softmodem not found in $BUILD"
  echo "Build OAI first:  bash oai/setup_oai.sh"
  exit 1
fi

mkdir -p "$OUT_DIR"
cd "$BUILD"
rm -f reconfig.raw rbconfig.raw

echo "[gNB] starting (phy-test + rfsim, server)..."
./nr-softmodem -O "$CONF" --rfsim --phy-test "--rfsimulator.[0].serveraddr" server \
    > "$OUT_DIR/gnb.log" 2>&1 &
GNB=$!

# Wait for the gNB to write the RRC config files the UE needs.
for _ in $(seq 1 40); do [ -f reconfig.raw ] && break; sleep 1; done
if [ ! -f reconfig.raw ]; then
  echo "gNB failed to initialise (no reconfig.raw). Check $OUT_DIR/gnb.log"
  kill "$GNB" 2>/dev/null
  exit 1
fi

echo "[UE] starting (connect to 127.0.0.1)..."
./nr-uesoftmodem --rfsim --phy-test "--rfsimulator.[0].serveraddr" 127.0.0.1 \
    --reconfig-file "$BUILD/reconfig.raw" --rbconfig-file "$BUILD/rbconfig.raw" \
    > "$OUT_DIR/ue.log" 2>&1 &
UE=$!

echo "[run] capturing KPIs for ${DURATION}s..."
sleep "$DURATION"

kill "$UE" "$GNB" 2>/dev/null; sleep 2
pkill -f nr-uesoftmodem 2>/dev/null; pkill -f nr-softmodem 2>/dev/null

echo
echo "Logs:  $OUT_DIR/gnb.log , $OUT_DIR/ue.log"
echo "Parse: python3 oai/collect_kpis.py $OUT_DIR/gnb.log $OUT_DIR/kpis.csv"
