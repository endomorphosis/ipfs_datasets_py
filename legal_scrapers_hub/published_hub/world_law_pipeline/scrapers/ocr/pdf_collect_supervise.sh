#!/bin/bash
# keeps ONE pdf_collect.py (--workers 2, min-free 10G) alive, re-checking every 30 min; hourly checkpoint to store; halts on low disk / high RSS; TERM if events.log stale >90min while collector has been running >90min
cd /workspace/world_law
S=/cursor/stores/store-3ee13b5a-7cbf-4070-915c-99ab026720b3/pdf_collector
export REQUESTS_CA_BUNDLE=$PWD/ocr/_cache/ca_bundle_plus_digicert_g2.pem SSL_CERT_FILE=$PWD/ocr/_cache/ca_bundle_plus_digicert_g2.pem
L=staging/pdf/_logs/supervisor.log; last=0
EV=staging/pdf/_logs/events.log
while true; do
  free=$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)
  pid=$(pgrep -f '^/workspace/hf-venv/bin/python ocr/pdf_collect.py' | head -1)
  if [ "$free" -lt 10 ]; then echo "$(date) free=${free}G <10, stopping" >>$L; [ -n "$pid" ] && kill -TERM $pid; exit 0; fi
  if [ -n "$pid" ]; then
    rss=$(awk '/VmRSS/{print $2}' /proc/$pid/status)
    if [ "${rss:-0}" -gt 1500000 ]; then
      echo "$(date) rss=${rss}kB >1.5GB, TERM" >>$L
      kill -TERM $pid
    elif [ -f "$EV" ]; then
      age=$(( $(date +%s) - $(stat -c %Y "$EV") ))
      etimes=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -dc 0-9)
      if [ "${etimes:-0}" -gt 5400 ] && [ "$age" -gt 5400 ]; then
        echo "$(date) events.log stale ${age}s (proc ${etimes}s) >90min, TERM $pid" >>$L
        kill -TERM $pid
      fi
    fi
  else
    setsid nohup /workspace/hf-venv/bin/python ocr/pdf_collect.py --workers 2 --min-free-gb 10 --cap-gb 10 >>staging/pdf/_logs/collector_stdout.log 2>&1 </dev/null &
    echo "$(date) started pid $!" >>$L
  fi
  if [ $(( $(date +%s) - last )) -ge 3600 ]; then
    mkdir -p $S/checkpoint; cp ocr/pdf_collect.py ocr/pdf_collect_supervise.sh $S/; cp staging/pdf/_state/done.txt staging/pdf/_state/attempts.json $S/checkpoint/
    echo "$(date -Is) fetched_lines=$(wc -l <staging/pdf/_logs/fetched.jsonl) done_lines=$(wc -l <staging/pdf/_state/done.txt)" > $S/checkpoint/counts.txt; last=$(date +%s)
  fi
  sleep 1800
done
