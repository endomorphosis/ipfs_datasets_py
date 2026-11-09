#!/usr/bin/env bash
# LII archive targets (2026-10-23): retry the 10-doc CC-only test until CC index is free, validate (lii_check.py),
# then enroll into wayback_resume_loop via resume_full.flag. TZ_lii_gn (government notices) is enrolled only after
# TZ_lii's full run has finished (flag gone), so notices go last. Never touches other targets.
HERE=/workspace/world_law/pipeline/scrapers/national/archive; cd $HERE
L=/workspace/world_law/staging/national/_logs/archive; W=/workspace/world_law/staging/national/_archive_work
PY=/workspace/world_law/pipeline/venv/bin/python
export PYTHONUNBUFFERED=1 ARCHIVE_LANE=national MALLOC_ARENA_MAX=2
log(){ echo "$(date '+%F %T') lii_enroll $*" >> $L/lii_enroll.log; }
test_ok(){ $PY lii_check.py $1 ${2:-10} >> $L/lii_enroll.log 2>&1; }
for t in TZ_lii GH_lii UG_lii TZ_lii_gn; do
  for i in $(seq 1 72); do       # up to ~12 h of retries, every 10 min
    test_ok $t && break
    prlimit --as=629145600 nice -n 10 $PY run_archive.py $t --max-fetch 10 --chunk 25 --no-wayback >> $L/small_$t.log 2>&1
    log "small $t attempt $i rc=$?"
    test_ok $t && break
    sleep 600
  done
  if test_ok $t; then log "TEST OK $t"; else log "TEST NOT OK $t after retries; not enrolled"; fi
done
for t in TZ_lii GH_lii UG_lii; do test_ok $t && touch $W/$t/resume_full.flag && log "enrolled $t (resume_full.flag)"; done
if test_ok TZ_lii_gn; then
  while [ -e $W/TZ_lii/resume_full.flag ]; do sleep 900; done
  touch $W/TZ_lii_gn/resume_full.flag; log "enrolled TZ_lii_gn after TZ_lii full pass"
fi
log "exit"
