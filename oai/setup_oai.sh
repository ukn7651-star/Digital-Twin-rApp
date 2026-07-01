#!/usr/bin/env bash
# Build the full OpenAirInterface engine (gNB + UE) from source.
#
# Safe in a sandboxed CPU container: forces GCC (clang cannot build OAI) and the
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

echo "[2/4] Clone OAI (shallow)..."
[ -d "$OAI_DIR" ] || git clone --depth 1 https://gitlab.eurecom.fr/oai/openairinterface5g.git "$OAI_DIR"

echo "[3/4] Install OAI build dependencies..."
cd "$OAI_DIR/cmake_targets"
sudo -E ./build_oai -I

echo "[4/4] Build gNB + UE with GCC (clang crashes on OAI's MMX intrinsics)..."
CC=gcc CXX=g++ ./build_oai --gNB --nrUE --ninja

echo
echo "Done. Binaries:"
ls -lh "$OAI_DIR/cmake_targets/ran_build/build/nr-softmodem" \
       "$OAI_DIR/cmake_targets/ran_build/build/nr-uesoftmodem"
echo "Now run:  bash oai/run_phytest.sh"
