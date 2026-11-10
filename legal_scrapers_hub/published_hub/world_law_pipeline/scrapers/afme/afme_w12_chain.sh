#!/bin/bash
# WAVE 12 chain (afme lane), modeled on afme_w11_chain.sh. Waits for the wave-11 chain (PID 1066592) to exit first (lane = 1 crawl / 1 Wayback worker).
# Countries = biggest empty AFME countries: MG SN ET ML GN RW. Hosts from afme/w12/<cc>_hosts.csv (afme_w12_discover.py: candidate-CSV official sites + gov/commune naming patterns, DoH-verified).
# Step 0: NG state-ID fix (afme_ng_adm1fix.py -> iso:NG-XX adm1 copies) then stage NG.
# Logs: afme/_w12_chain.log, afme/_<cc>_w12_test.log, afme/_<cc>_w12_full.log, afme/_stage_w12.log; done list afme/_w12_done.txt; no-host list afme/_w12_nohosts.txt.
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_w12_chain.log; D=afme/_w12_done.txt; NH=afme/_w12_nohosts.txt; touch $D $NH
echo "$(date) w12 waiting for w11 chain PID 1066592" >> $L
while kill -0 1066592 2>/dev/null || pgrep -f "afme_w11_chain.sh|afme_w10_taskA_rerun.sh|afme_arch11.py|afme_live11.py" >/dev/null; do sleep 120; done
while pgrep -f afme_w12_discover.py >/dev/null || [ $(ls afme/w12/*_hosts.csv 2>/dev/null | wc -l) -lt 6 ]; do sleep 60; done   # host discovery must finish first
echo "$(date) w11 gone + discovery done, starting w12" >> $L
PY=../pipeline/venv/bin/python; VP=.afme_venv/bin/python
ORDER="MG:fr:both SN:fr:both ET:en:both ML:fr:both GN:fr:both RW:en:both" # MR:fr:both LR:en:both CF:fr:both CG:fr:both SS:en:both ZW:en:both GA:fr:both UG:en:arch KM:fr:both TD:fr:both YE:ar:both ZM:en:both BW:en:both LS:en:both SL:en:both KW:ar:both ER:en:both MW:en:both SZ:en:both SO:en:both IR:fa:both TR:tr:both NG:en:both GH:en:both IL:he:both KE:en:both"
log(){ echo "$(date) $*" >> $L; }
waitdisk(){ while [ "$(df --output=avail -B1M /workspace | tail -1 | tr -d ' ')" -lt 20480 ]; do log "PAUSED: /workspace free < 20 GiB (no writes)"; sleep 300; done; }
step(){ # step <logfile> <cmd...> : run through the slot/RSS guard; exit 3 = disk floor -> pause and resume (steps are resumable)
  local lf=$1; shift; local n=0 rc
  while [ $n -lt 40 ]; do waitdisk; ./afme_slot.sh x "$@" >> $lf 2>&1; rc=$?; [ $rc -ne 3 ] && return $rc; n=$((n+1)); log "disk-floor exit, pausing"; sleep 300; done; return 3; }
stage(){ waitdisk; $VP afme_stage.py $1 >> afme/_stage_w12.log 2>&1; log "$1 staged: $(tail -1 afme/_stage_w12.log | cut -c1-300)"; }
nlines(){ $VP - <<P
import json;print(len(json.load(open("afme/$1"))["places"]))
P
}
livephase(){ # $1=cc $2=lang $3=mode
  local cc=$1 lang=$2 mode=$3 lc=$(echo $1 | tr A-Z a-z)
  log "=== $cc LIVE ($lang $mode)"; waitdisk
  $VP afme_w12_cfg.py $cc $lang $mode >> afme/_${lc}_w12_test.log 2>&1 || { log "$cc cfg build FAILED (skipped)"; return; }
  nl=$(nlines ${lc}_live_w12_cfg.json); na=$(nlines ${lc}_arch_w12_cfg.json)
  if [ "$nl" = 0 ] && [ "$na" = 0 ]; then log "$cc no usable official hosts (aggregators only) -> $NH"; echo "$cc" >> $NH; echo "$cc" >> $D; return; fi
  [ "$nl" -gt 0 ] || return
  [ -f afme/$cc/.w12_live_done ] && return
  rm -f afme/$cc/*.${lc}_live_w12t.test.jsonl
  step afme/_${lc}_w12_test.log $VP -W ignore afme_live11.py afme/${lc}_live_w12_test_cfg.json 0 test
  if $PY afme_gate.py $cc .${lc}_live_w12t.test.jsonl --allow-empty >> $L 2>&1; then
    step afme/_${lc}_w12_full.log $VP -W ignore afme_live11.py afme/${lc}_live_w12_cfg.json 0; log "$cc live full exit $?"; stage $cc
  else log "$cc LIVE test gate FAILED (live skipped; places fall back to archive)"; fi
  touch afme/$cc/.w12_live_done
  $VP afme_w12_fallback.py $cc >> $L 2>&1
}
archphase(){ # $1=cc
  local cc=$1 lc=$(echo $1 | tr A-Z a-z) deferred=0
  grep -qx $cc $D && return
  [ -f afme/${lc}_arch_w12_cfg.json ] || return
  na=$(nlines ${lc}_arch_w12_cfg.json); [ "$na" = 0 ] && { echo $cc >> $D; return; }
  log "=== $cc ARCH ($na places)"
  while pgrep -f "afme_w10_taskA_rerun.sh|afme_w10_region_chain.sh|afme_w10_au_arch_chain.sh" >/dev/null; do sleep 60; done   # one Wayback worker for the lane
  rm -f afme/$cc/*.${lc}_arch_w12t.test.jsonl
  step afme/_${lc}_w12_test.log $PY -W ignore afme_arch11.py afme/${lc}_arch_w12_test_cfg.json test
  if $PY afme_gate.py $cc .${lc}_arch_w12t.test.jsonl --allow-empty >> $L 2>&1; then
    step afme/_${lc}_w12_full.log $PY -W ignore afme_arch11.py afme/${lc}_arch_w12_cfg.json; log "$cc arch full exit $?"
    tail -5 afme/_${lc}_w12_full.log | grep -q DEFERRED_LEFT && deferred=1
    stage $cc
  else log "$cc ARCH test gate FAILED (arch skipped; not retried)"; fi
  [ $deferred = 1 ] && log "$cc has Wayback-deferred places: NOT marked done (retry pass)" || echo $cc >> $D
}
[ -f afme/.ng_adm1fix_done ] || { waitdisk; $VP afme_ng_adm1fix.py >> $L 2>&1 && stage NG && touch afme/.ng_adm1fix_done; }
for it in $ORDER; do cc=${it%%:*}; r=${it#*:}; livephase $cc ${r%%:*} ${r#*:}; done
for pass in 1 2; do for it in $ORDER; do archphase ${it%%:*}; done; done
log "wave 12 chain finished"
