#!/usr/bin/env bash
# Build the full OpenAirInterface engine (gNB + UE) from source.
#
# Safe in a CPU-only host: forces GCC (clang cannot build OAI) and the
# binaries are meant to be run as a non-root user (see run_phytest.sh).
#
# Usage:  bash oai/setup_oai.sh [install_dir]     (default: $HOME)
set -euo pipefail

INSTALL_DIR="${1:-$HOME}"
OAI_DIR="$INSTALL_DIR/openairinterface5g"
export DEBIAN_FRONTEND=noninteractive

echo "[1/4] System dependencies..."
echo 'iperf3 iperf3/start_daemon boolean false' | sudo debconf-set-selections || true
sudo -E apt-get update -qq
sudo -E apt-get install -y iperf3 ninja-build g++ libstdc++-14-dev

echo "[2/5] Clone OAI (shallow)..."
[ -d "$OAI_DIR" ] || git clone --depth 1 https://gitlab.eurecom.fr/oai/openairinterface5g.git "$OAI_DIR"

echo "[3/5] Apply the Sionna RT channel-injection patch..."
# Adds oai_rt_inject_channel() so the rfsimulator transmits over the ray-traced
# channel (env OAI_RT_TAPS). Idempotent: skip if already applied.
PATCH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/patches/rt_channel_injection.patch"
cd "$OAI_DIR"
if ! grep -q "oai_rt_inject_channel" openair1/SIMULATION/TOOLS/random_channel.c; then
  git apply "$PATCH" && echo "  patch applied."
else
  echo "  patch already present, skipping."
fi

echo "[4/5] Install OAI build dependencies..."
cd "$OAI_DIR/cmake_targets"
sudo -E ./build_oai -I

echo "[5/5] Build gNB + UE with GCC (clang crashes on OAI's MMX intrinsics)..."
CC=gcc CXX=g++ ./build_oai --gNB --nrUE --ninja

echo
echo "Done. Binaries:"
ls -lh "$OAI_DIR/cmake_targets/ran_build/build/nr-softmodem" \
       "$OAI_DIR/cmake_targets/ran_build/build/nr-uesoftmodem"
echo "Now run:  bash oai/run_phytest.sh"
