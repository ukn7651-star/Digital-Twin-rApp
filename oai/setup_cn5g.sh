#!/usr/bin/env bash
# Bring up the OAI 5G Core (oai-cn5g) via Docker Compose.
#
# Requires Docker + docker compose AND a kernel with SCTP + TUN
# (run `bash oai/check_host.sh` first). The 5G core is required for Standalone
# (SA) mode -> multi-UE runs and iperf3 goodput.
#
# NOTE: the compose file bind-mounts conf/config.yaml, the subscriber DB, and a
# healthcheck script; these must exist locally BEFORE `up` or Docker silently
# creates them as (root-owned) directories and the NFs fail to start. This script
# fetches the whole set.
#
# Usage:  bash oai/setup_cn5g.sh [install_dir]     (default: $HOME/oai-cn5g)
set -euo pipefail

CN_DIR="${1:-$HOME/oai-cn5g}"
BR="${OAI_BRANCH:-develop}"
BASE="https://gitlab.eurecom.fr/oai/openairinterface5g/-/raw/$BR/doc/tutorial_resources/oai-cn5g"

command -v docker >/dev/null 2>&1 || { echo "docker not found (install: curl -fsSL https://get.docker.com | sudo sh)"; exit 1; }
sudo docker compose version >/dev/null 2>&1 || { echo "'docker compose' plugin not found"; exit 1; }

# If the host root fs is itself overlay (nested/container), Docker's overlay2
# driver cannot stack -> fall back to vfs (slower, more disk, but always works).
if [ ! -f /etc/docker/daemon.json ] && mount 2>/dev/null | grep -q "overlay on / "; then
  echo "[cn5g] root fs is overlay; setting Docker storage-driver=vfs"
  echo '{"storage-driver":"vfs"}' | sudo tee /etc/docker/daemon.json >/dev/null
  sudo systemctl restart docker 2>/dev/null || sudo service docker restart 2>/dev/null || true
  sleep 3
fi

mkdir -p "$CN_DIR/conf" "$CN_DIR/database" "$CN_DIR/healthscripts"
cd "$CN_DIR"

echo "[1/4] Fetching CN5G compose + config set ($BR) ..."
for f in docker-compose.yaml conf/config.yaml conf/sip.conf conf/users.conf \
         database/oai_db.sql healthscripts/mysql-healthcheck.sh; do
  if [ ! -s "$f" ]; then
    curl -fsSL "$BASE/$f" -o "$f" || { echo "  fetch failed: $f"; exit 1; }
  fi
done
chmod +x healthscripts/mysql-healthcheck.sh

echo "[2/4] Pulling core images ..."
sudo docker compose pull

echo "[3/4] Starting the 5G core ..."
sudo docker compose up -d
sleep 8

echo "[4/4] Status:"
sudo docker compose ps

cat <<'EON'

All NFs (esp. oai-amf and oai-upf) must reach 'healthy'.
  * oai-amf exiting (139)  -> kernel has no SCTP  (run oai/check_host.sh)
  * oai-upf 'open /dev/net/tun' -> kernel has no TUN driver
Subscribers IMSI 001010000000001..004 are preloaded in database/oai_db.sql.
Stop with:  (cd ~/oai-cn5g && sudo docker compose down)
EON
