#!/bin/bash
# Sequential Wayback queue (one job, one connection) for Peachjam LIIs.
cd /workspace/world_caselaw/amea
for spec in "zimlii.org zw amea-zimlii-wb" "malawilii.org mw amea-malawilii-wb" "namiblii.org na amea-namiblii-wb" "zambialii.org zm amea-zambialii-wb"; do
  set -- $spec
  python3 scrapers/caselaw/peachjam.py --site $1 --cc $2 --src $3 --wayback --delay 4 --shard-rows 200 >> logs/$3.log 2>&1
done
