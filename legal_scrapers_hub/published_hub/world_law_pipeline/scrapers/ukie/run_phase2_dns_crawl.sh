#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Phase 2: crawl parish/town council sites found by DNS discovery (places.mode='council_site_dns', status todo), live only
# (--no-archive), phase-2 bye-law gate + PHASE2_PAGES budget (both automatic for phase-2 rows). Resumable: each round
# re-selects todo places; every crawled place leaves 'todo'. Sleeps ~30 min between rounds for newly discovered sites;
# exits once run_discover_dns.sh has printed DISCOVER_DNS_DONE_ALL and no such place is left.
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
DNSLOG=$S/logs/discover_dns_20261018T1822.log
PF=$S/phase2_dns_todo.txt
while :; do
  dns_done=0; grep -q DISCOVER_DNS_DONE_ALL "$DNSLOG" && dns_done=1     # read BEFORE selecting: no race at the end
  N=$($PY -c "
import sqlite3; c=sqlite3.connect('file:$S/ukie_state.sqlite?mode=ro', uri=True)
ids=[r[0] for r in c.execute(\"SELECT place_id FROM places WHERE phase=2 AND status='todo' AND mode='council_site_dns' AND COALESCE(site,'')<>'' ORDER BY place_id\")]
open('$PF.tmp','w').write(''.join(i+'\n' for i in ids)); print(len(ids))") || { sleep 1800; continue; }
  mv $PF.tmp $PF
  echo "$(date '+%FT%T%z') round: $N todo DNS-discovered phase-2 places (dns_done=$dns_done)"
  if [ "$N" -gt 0 ]; then
    $PY -u councils.py run --no-archive --places-file $PF
  elif [ $dns_done = 1 ]; then
    break
  fi
  if [ $dns_done = 1 ]; then sleep 60; else sleep 1800; fi   # discovery finished: short re-check (a StopRun leaves todo)
done
echo PHASE2_DNS_CRAWL_DONE
