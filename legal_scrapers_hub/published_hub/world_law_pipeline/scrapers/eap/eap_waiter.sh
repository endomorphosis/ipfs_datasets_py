#!/bin/bash
# usage: eap_waiter.sh <name> <stages> [wait_for_stage]
# runner exit 6 = only deferred items left (429/5xx cool-down) -> sleep until arch_ckpt/run.retry_at (min not_before, >=60 s)
# exit 3 (archives/breaker down) -> retry 30 min; other failure -> 10 min; all done -> recheck after 24 h
R=/workspace/world_law/pipeline/scrapers/eap; C=/workspace/world_law/staging/eap/_eap_work/arch_ckpt
mkdir -p /workspace/world_law/out/eap/_logs; cd $R; export ARCHIVE_LANE=eap
N=$1; ST=$2; DEP=$3; echo $$ > $C/../_$N.pid
while true; do
  bash /workspace/world_law/pipeline/scrapers/eap/backup_eap.sh
  if [ -n "$DEP" ] && [ ! -f $C/$DEP.FINISHED ]; then echo "$(date '+%F %T') waiting for $DEP"; sleep 600; continue; fi
  fr=$(df --output=avail -BG /workspace | tail -1 | tr -dc 0-9)
  if [ "$fr" -lt 20 ]; then echo "$(date '+%F %T') low disk ${fr}G"; sleep 1800; continue; fi
  ARCHIVE_LANE=eap timeout 12h /workspace/world_law/pipeline/scrapers/eap/.venv/bin/python -u $R/eap_archive_runner.py $ST; rc=$?
  echo "$(date '+%F %T') runner exit $rc"
  case $rc in
    0) sleep 86400; for s in ${ST//,/ }; do [ -f $C/$s.FINISHED ] && mv $C/$s.FINISHED $C/$s.FINISHED.prev; done;;
    6) nb=$(cat $C/run.retry_at 2>/dev/null | cut -d. -f1); now=$(date +%s); w=$(( ${nb:-0} - now )); [ $w -lt 60 ] && w=60; [ $w -gt 21600 ] && w=21600
       echo "$(date '+%F %T') deferred; sleeping ${w}s"; sleep $w;;
    3) sleep 1800;;
    *) sleep 600;;
  esac
done
