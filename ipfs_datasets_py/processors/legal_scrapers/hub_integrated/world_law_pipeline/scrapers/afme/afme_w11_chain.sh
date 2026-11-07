#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# WAVE 11 chain (afme lane). Sequential: ONE crawl process at a time (total RSS << 480 MiB; <=1 Wayback worker for the lane), resumable.
# Order = AFME countries by missing-place count in state/ipfs_missing_places_20261020.csv, then the user-named countries that have 0 rows in that file (by pipeline/state/coverage_gaps.csv uncovered).
# Phase 1 (live, all countries in order) then phase 2 (archive, all countries in order; waits for Task A / other Wayback users so the lane has ONE Wayback worker) then phase 3 = retry of deferred countries.
# Per country: build cfgs (robots probe, 1 GET/host) -> LIVE test(<=20) -> afme_gate (0 bad) -> LIVE full -> stage -> add live failures to ARCH list -> ARCH test(<=20) -> gate -> ARCH full (CC index then Wayback via ratelimit breaker) -> stage.
# Disk: never writes below 38 GiB free on /workspace (pauses and polls every 5 min; deletes nothing). Done list: afme/_w11_done.txt (a country with deferred Wayback places is NOT marked done; pass 2 retries it).
# Logs: afme/_w11_chain.log, afme/_<cc>_w11_test.log, afme/_<cc>_w11_full.log, afme/_stage_w11.log
cd ${WORLD_LAW_ROOT}/out; export ARCHIVE_LANE=afme; L=afme/_w11_chain.log; D=afme/_w11_done.txt; NH=afme/_w11_nohosts.txt; touch $D $NH
PY=../pipeline/venv/bin/python; VP=.afme_venv/bin/python
ORDER="BF:fr:both MR:fr:both LR:en:both CF:fr:both CG:fr:both SS:en:both ZW:en:both GA:fr:both UG:en:arch KM:fr:both TD:fr:both YE:ar:both ZM:en:both BW:en:both LS:en:both SL:en:both KW:ar:both ER:en:both MW:en:both SZ:en:both SO:en:both IR:fa:both TR:tr:both NG:en:both GH:en:both IL:he:both KE:en:both"
log(){ echo "$(date) $*" >> $L; }
waitdisk(){ while [ "$(df --output=avail -B1M /workspace | tail -1 | tr -d ' ')" -lt 38912 ]; do log "PAUSED: /workspace free < 38 GiB (no writes)"; sleep 300; done; }
step(){ # step <logfile> <cmd...> : run through the slot/RSS guard; exit 3 = disk floor -> pause and resume (steps are resumable)
  local lf=$1; shift; local n=0 rc
  while [ $n -lt 40 ]; do waitdisk; ./afme_slot.sh x "$@" >> $lf 2>&1; rc=$?; [ $rc -ne 3 ] && return $rc; n=$((n+1)); log "disk-floor exit, pausing"; sleep 300; done; return 3; }
stage(){ waitdisk; $VP afme_stage.py $1 >> afme/_stage_w11.log 2>&1; log "$1 staged: $(tail -1 afme/_stage_w11.log | cut -c1-300)"; }
nlines(){ $VP - <<P
import json;print(len(json.load(open("afme/$1"))["places"]))
P
}
livephase(){ # $1=cc $2=lang $3=mode
  local cc=$1 lang=$2 mode=$3 lc=$(echo $1 | tr A-Z a-z)
  log "=== $cc LIVE ($lang $mode)"; waitdisk
  $VP afme_w11_cfg.py $cc $lang $mode >> afme/_${lc}_w11_test.log 2>&1 || { log "$cc cfg build FAILED (skipped)"; return; }
  nl=$(nlines ${lc}_live_w11_cfg.json); na=$(nlines ${lc}_arch_w11_cfg.json)
  if [ "$nl" = 0 ] && [ "$na" = 0 ]; then log "$cc no usable official hosts (aggregators only) -> $NH"; echo "$cc" >> $NH; echo "$cc" >> $D; return; fi
  [ "$nl" -gt 0 ] || return
  [ -f afme/$cc/.w11_live_done ] && return
  rm -f afme/$cc/*.${lc}_live_w11t.test.jsonl
  step afme/_${lc}_w11_test.log $VP -W ignore afme_live11.py afme/${lc}_live_w11_test_cfg.json 0 test
  if $PY afme_gate.py $cc .${lc}_live_w11t.test.jsonl --allow-empty >> $L 2>&1; then
    step afme/_${lc}_w11_full.log $VP -W ignore afme_live11.py afme/${lc}_live_w11_cfg.json 0; log "$cc live full exit $?"; stage $cc
  else log "$cc LIVE test gate FAILED (live skipped; places fall back to archive)"; fi
  touch afme/$cc/.w11_live_done
  $VP afme_w11_fallback.py $cc >> $L 2>&1
}
archphase(){ # $1=cc
  local cc=$1 lc=$(echo $1 | tr A-Z a-z) deferred=0
  grep -qx $cc $D && return
  [ -f afme/${lc}_arch_w11_cfg.json ] || return
  na=$(nlines ${lc}_arch_w11_cfg.json); [ "$na" = 0 ] && { echo $cc >> $D; return; }
  log "=== $cc ARCH ($na places)"
  while pgrep -f "afme_w10_taskA_rerun.sh|afme_w10_region_chain.sh|afme_w10_au_arch_chain.sh" >/dev/null; do sleep 60; done   # one Wayback worker for the lane
  rm -f afme/$cc/*.${lc}_arch_w11t.test.jsonl
  step afme/_${lc}_w11_test.log $PY -W ignore afme_arch11.py afme/${lc}_arch_w11_test_cfg.json test
  if $PY afme_gate.py $cc .${lc}_arch_w11t.test.jsonl --allow-empty >> $L 2>&1; then
    step afme/_${lc}_w11_full.log $PY -W ignore afme_arch11.py afme/${lc}_arch_w11_cfg.json; log "$cc arch full exit $?"
    tail -5 afme/_${lc}_w11_full.log | grep -q DEFERRED_LEFT && deferred=1
    stage $cc
  else log "$cc ARCH test gate FAILED (arch skipped; not retried)"; fi
  [ $deferred = 1 ] && log "$cc has Wayback-deferred places: NOT marked done (retry pass)" || echo $cc >> $D
}
for it in $ORDER; do cc=${it%%:*}; r=${it#*:}; livephase $cc ${r%%:*} ${r#*:}; done
for pass in 1 2; do for it in $ORDER; do archphase ${it%%:*}; done; done
log "wave 11 chain finished"
