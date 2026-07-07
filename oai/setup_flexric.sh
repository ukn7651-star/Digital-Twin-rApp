#!/usr/bin/env bash
# Build FlexRIC (O-RAN near-RT RIC) and point to the KPM monitoring xApp.
#
# =============================================================================
# NOT YET INTEGRATION-TESTED END-TO-END. Requires a full Linux host with the FlexRIC
# build toolchain (cmake, SWIG, recent gcc, Flatbuffers). Commands follow the
# FlexRIC README / OAI FlexRIC tutorial; adapt to your host. FlexRIC connects to
# OAI's E2 agent, which the gNB exposes when built with the E2 option.
# =============================================================================
#
# After this: run the RIC (nearRT-RIC), start the gNB with the E2 agent, then run
# the KPM xApp to stream per-UE KPMs (RSRP/MCS/BLER/throughput) that feed the rApp
# decision in oai/rapp_closed_loop.py.
#
# Usage:  bash oai/setup_flexric.sh [install_dir]     (default: $HOME/flexric)
set -euo pipefail

FLEXRIC_DIR="${1:-$HOME/flexric}"

for t in cmake gcc g++ git; do command -v "$t" >/dev/null 2>&1 || { echo "$t not found"; exit 1; }; done

[ -d "$FLEXRIC_DIR" ] || git clone https://gitlab.eurecom.fr/mosaic5g/flexric.git "$FLEXRIC_DIR"
cd "$FLEXRIC_DIR"

echo "[1/3] Configure ..."
mkdir -p build && cd build
cmake .. -DXAPP_MULTILANGUAGE=OFF

echo "[2/3] Build RIC + service models + example xApps ..."
cmake --build . -j"$(nproc)"

echo "[3/3] Install service models ..."
sudo make install || echo "  (install step may need sudo; re-run if it failed)"

cat <<'EON'

Built. Typical run order on the host:
  1) Start the near-RT RIC:      ./build/examples/ric/nearRT-RIC
  2) Start OAI gNB with E2 agent (gNB built with the E2 option; conf has an
     e2_agent block pointing at the RIC IP).
  3) Start the KPM monitor xApp: ./build/examples/xApp/c/monitor/xapp_kpm_moni
     -> streams per-UE KPMs (E2SM-KPM v3). Log/export these to a CSV and feed
        oai/rapp_closed_loop.py, or wire the rApp to act directly on the E2 RC
        service model for closed-loop control.
EON
