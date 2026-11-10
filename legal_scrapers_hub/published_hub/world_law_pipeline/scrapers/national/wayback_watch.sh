#!/usr/bin/env bash
# Probe web.archive.org every 30 min. When reachable: robots-gated retest of archive-dependent
# collectors (smoke_retest.py), then queue the ones that staged docs (MAX_CONC=2, separate queue).
N=/workspace/world_law/pipeline/scrapers/national; L=/workspace/world_law/staging/national/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
while true; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 "https://web.archive.org/cdx/search/cdx?url=example.com&limit=1")
  echo "$(date '+%F %T %Z') wayback cdx http=$code"
  if [ "$code" = "200" ]; then
    echo "$(date '+%F %T %Z') wayback UP -> retest"
    SMOKE_TIMEOUT=300 SMOKE_CONC=4 $PY $N/smoke_retest.py $(cat $L/wayback_retest_ccs.txt) > $L/smoke/_retest_driver.log 2>&1
    ARGS=$($PY - <<'PY'
import json
cat={e['country_code']:e['collector'] for e in json.load(open('/workspace/world_law/pipeline/scrapers/national/snapshot_catalog.json'))['entries'] if not e.get('alias_of')}
R=[json.loads(l) for l in open('/workspace/world_law/staging/national/_logs/smoke/results_retest.jsonl')]
import sys; sys.path.insert(0,'/workspace/world_law/pipeline/scrapers/national/common')
from robots import robots_for, UA
meta=json.load(open('/workspace/world_law/staging/national/_collector_meta.json'))
ok=[]
for r in R:
    if r['status']!='works': continue
    hosts=meta[r['cc']]['hosts'][:2]
    good=all(robots_for('https://'+h+'/')[0].can_fetch(UA,'https://'+h+'/') for h in hosts)
    print(r['cc'],'robots', 'ok' if good else 'DISALLOWED', file=sys.stderr)
    if good: ok.append(f"{r['cc']}:{cat[r['cc']]}")
print(' '.join(ok))
PY
)
    echo "$(date '+%F %T %Z') queue: $ARGS"
    [ -n "$ARGS" ] && MAX_CONC=2 nohup $PY $N/queue_full.py $ARGS > $L/full/_queue_wayback.log 2>&1 &
    echo "queue pid $!"; break
  fi
  sleep 1800
done
