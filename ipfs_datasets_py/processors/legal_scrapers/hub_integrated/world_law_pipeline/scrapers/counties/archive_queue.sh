#!/bin/sh
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Detached archive-fallback queue. Each round: every DE Lower Saxony config, every FR RAA config, Harris TX.
# archive_retry.py skips URLs already staged/processed for the place, so rounds are idempotent.
cd ${WORLD_LAW_ROOT}/pipeline/scrapers/counties
while pgrep -f "_retry.json" >/dev/null; do sleep 60; done
for round in 1 2 3 4 5 6; do
  python3 - <<'PY'
import json,glob
for f in glob.glob('fr_raa_fr-*.json'):
    if f.endswith('_archive.json'): continue
    c=json.load(open(f)); c['archive_policy']='archived_live_download_refused'; json.dump(c,open(f.replace('.json','_archive.json'),'w'),ensure_ascii=False,indent=1)
PY
  for c in harris_tx_retry.json $(ls de_nds_landkreis_*.json | grep -vE '_retry|_archive') $(ls fr_raa_fr-*_archive.json); do
    df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
    echo "== round $round $c $(date)"; timeout 3000 python3 -u ../../../pipeline/scrapers/counties/archive_retry.py $c 45 2>&1 | grep -E '^(todo|OK|MISS|INVALID|written)'
  done
  sleep 1800
done
