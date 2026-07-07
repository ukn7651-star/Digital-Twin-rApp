#!/usr/bin/env bash
# Bring up the OAI 5G Core (oai-cn5g) via Docker Compose.
#
# =============================================================================
# NOT YET INTEGRATION-TESTED END-TO-END. Requires a full Linux host with Docker +
# docker compose (a minimal host may lack both). Commands follow the official
# OAI CN5G docker-compose tutorial; adapt versions/paths to your host.
# =============================================================================
#
# The 5G Core is required for Standalone (SA) mode, which in turn is required for
# multi-UE runs and iperf3 goodput (phy-test is single-UE, no core, no goodput).
#
# Usage:  bash oai/setup_cn5g.sh [install_dir]     (default: $HOME/oai-cn5g)
set -euo pipefail

CN_DIR="${1:-$HOME/oai-cn5g}"

command -v docker >/dev/null 2>&1 || { echo "docker not found (needs a full host)"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "'docker compose' plugin not found"; exit 1; }

mkdir -p "$CN_DIR"
cd "$CN_DIR"

# Official minimalist CN5G docker-compose set (basic deployment).
if [ ! -f docker-compose.yaml ]; then
  echo "[1/3] Fetching OAI CN5G docker-compose (basic) ..."
  wget -q https://gitlab.eurecom.fr/oai/openairinterface5g/-/raw/develop/doc/tutorial_resources/oai-cn5g/docker-compose.yaml \
       -O docker-compose.yaml \
    || { echo "Fetch failed; copy oai-cn5g/docker-compose.yaml from the OAI repo manually."; exit 1; }
fi

echo "[2/3] Pulling core images ..."
docker compose pull

echo "[3/3] Starting the 5G core ..."
docker compose up -d
docker compose ps

echo
echo "Core is up. Add your UE IMSIs to the CN subscriber database (oai_db) so the"
echo "UEs in oai/run_multi_ue_rfsim.sh can register. Stop with: (cd $CN_DIR && docker compose down)"
