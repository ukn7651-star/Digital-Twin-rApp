#!/usr/bin/env bash
# Build the full OpenAirInterface engine (gNB + UE) from source.
#
# Reproduces the verified recipe in oai/BUILD_NOTES.md. Safe to run in a
# sandboxed CPU container: forces GCC (clang cannot build OAI) and does NOT use
# real-time scheduling at runtime (run the binaries as a non-root user).
#
# Intended to be called by the Cloud Agent environment config (startup script)
# so every VM boots with OAI ready, OR run manually once on a persistent box.
#
# Usage:  bash oai/setup_oai.sh [install_dir]   (default: $HOME)
set -euo pipefail

INSTALL_DIR="${1:-$HOME}"
OAI_DIR="$INSTALL_DIR/openairinterface5g"
export DEBIAN_FRONTEND=noninteractive

echo "[1/4] System dependencies (iperf3, ninja, matching libstdc++)..."
echo 'iperf3 iperf3/start_daemon boolean false' | sudo debconf-set-selections || true
sudo -E apt-get update -qq
sudo -E apt-get install -y iperf3 ninja-build g++ libstdc++-14-dev

echo "[2/4] Clone OAI (shallow)..."
if [ ! -d "$OAI_DIR" ]; then
  git clone --depth 1 https://gitlab.eurecom.fr/oai/openairinterface5g.git "$OAI_DIR"
fi

echo "[3/4] Install OAI build dependencies..."
cd "$OAI_DIR/cmake_targets"
sudo -E ./build_oai -I

echo "[4/4] Build gNB + UE with GCC (clang crashes on OAI's MMX intrinsics)..."
CC=gcc CXX=g++ ./build_oai --gNB --nrUE --ninja

BUILD="$OAI_DIR/cmake_targets/ran_build/build"
echo
echo "Done. Binaries:"
ls -lh "$BUILD/nr-softmodem" "$BUILD/nr-uesoftmodem"
echo
echo "Run (phy-test + rfsim) as a NON-ROOT user (no sudo):"
echo "  cd $BUILD"
echo "  CONF=$OAI_DIR/ci-scripts/conf_files/gnb.band78.106prb.rfsim.phytest-dora.conf"
echo "  ./nr-softmodem -O \$CONF --rfsim --phy-test --rfsimulator.[0].serveraddr server &"
echo "  ./nr-uesoftmodem --rfsim --phy-test --rfsimulator.[0].serveraddr 127.0.0.1 \\"
echo "      --reconfig-file \$(pwd)/reconfig.raw --rbconfig-file \$(pwd)/rbconfig.raw &"
