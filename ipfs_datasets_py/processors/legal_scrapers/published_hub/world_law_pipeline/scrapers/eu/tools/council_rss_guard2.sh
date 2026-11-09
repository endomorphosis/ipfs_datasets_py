#!/bin/bash
# 2026-10-30: RSS guard for council_docs.py ch/ua/by/cy runs (limit 460 MB -> graceful SIGTERM, relaunch same command).
# Exits after 30 min with no such runs. Log: staging/eu/_logs/council_rss_guard2.log
EU=/workspace/world_law/pipeline/scrapers/eu; L=/workspace/world_law/staging/eu/_logs; LIM=${LIM:-460000}
declare -A W=([ch]=2 [ua]=2 [by]=4 [cy]=4)   # 2026-10-30: cut to 2 for box RAM
log(){ echo "$(date '+%F %T %Z') $*" >> $L/council_rss_guard2.log; }
log "guard start"; idle=0
while true; do
  any=0
  for p in ch ua by cy; do
    pid=$(pgrep -f "council_docs.py $p run" | head -1); [ -z "$pid" ] && continue; any=1
    rss=$(ps -o rss= -p $pid | tr -d ' '); [ -z "$rss" ] && continue
    if [ "$rss" -gt "$LIM" ]; then
      log "$p pid $pid rss $rss KB: graceful restart"; kill -TERM $pid
      for i in $(seq 1 90); do kill -0 $pid 2>/dev/null || break; sleep 10; done
      kill -0 $pid 2>/dev/null && { log "$p $pid did not exit; left"; continue; }
      cd /workspace/world_law/staging/eu; MALLOC_ARENA_MAX=2 setsid nohup python3 $EU/council_docs.py $p run --workers ${W[$p]} >> $L/council_$p.nohup.out 2>&1 < /dev/null &
      sleep 5; log "$p relaunched: $(pgrep -f "council_docs.py $p run" | tr '\n' ' ')"
    fi
  done
  [ $any = 0 ] && idle=$((idle+1)) || idle=0; [ $idle -ge 30 ] && { log "no runs for 30 min; exit"; exit 0; }
  sleep 60
done
