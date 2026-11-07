#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# Archive retry for ALL places with pending archive_deferrals (GB phase 2 + IE phase 3, 2026-10-19). Exclusive (one ukie
# archive job at a time). Waits until `councils.py next-due` says something is due, then archive-queue passes
# (deferred places only once due; requeued doc URLs only for live-mode places), capped at 1 + 6 later passes.
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
. ./archive_passes.sh
ukie_archive_exclusive
PF=$S/archive_retry_all_places.txt
$PY -c "
import sqlite3; c=sqlite3.connect('file:$S/ukie_state.sqlite?mode=ro', uri=True)
ids=[r[0] for r in c.execute(\"SELECT DISTINCT d.place_id FROM archive_deferrals d JOIN places p USING(place_id) WHERE d.state='pending' AND p.status='deferred' ORDER BY p.phase DESC, d.place_id\")]
open('$PF.tmp','w').write(''.join(i+'\n' for i in ids)); print(len(ids), 'deferred places queued')" && mv $PF.tmp $PF
W=$($PY councils.py next-due --places-file $PF)
if [ "$W" != none ]; then
  echo "$(date '+%FT%T%z') first pass: earliest deferred place due in ${W}s"
  [ "$W" -gt 0 ] && sleep "$W"
  $PY -u councils.py run --archive-queue --archive-docs 8 --places-file $PF
  archive_later_passes $PF 6
fi
echo ARCHIVE_RETRY_ALL_DONE
