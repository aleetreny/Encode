#!/bin/zsh
# Resume the CEN snapshot. Pages already on disk are not requested again.
# Usage: scripts/cen_sip_resume.sh /path/to/.env.local   (file with COORDINADOR_API_KEY=...)
set -u
cd "$(dirname "$0")/.."
ENVF="$1"
for p in 04-large 05-catalogs 06-august; do
  echo "=== $p $(date -u +%H:%M:%S)"
  python3 scripts/cen_sip_snapshot.py "scripts/cen_sip_plans/$p.json" --env-file "$ENVF" || echo "FAILED $p"
done
python3 scripts/cen_sip_process.py
echo "=== DONE $(date -u +%H:%M:%S)"
