#!/bin/bash
# Keeps the live council_docs.py sk/cz/at runs under 500 MB (2026-10-18). Every 60 s: RSS > 460 MB -> graceful
# SIGTERM (flushes; done.sqlite resumes), then relaunch the same command. sk keeps its "sk; then at" chain.
EU=/workspace/world_law/pipeline/scrapers/eu; L=/workspace/world_law/staging/eu/_logs; LIM=${LIM:-460000}
log(){ echo "$(date '+%F %T %Z') $*" >> $L/council_rss_guard.log; }
cd $EU; log "guard start (limit ${LIM} KB)"; idle=0
while true; do
  any=0
  for p in sk cz at; do
    pid=$(pgrep -f "^python3 -u council_docs.py $p run" | head -1); [ -z "$pid" ] && continue; any=1
    rss=$(ps -o rss= -p $pid | tr -d ' '); [ -z "$rss" ] && continue
    if [ "$rss" -gt "$LIM" ]; then
      log "$p pid $pid rss ${rss} KB > limit: graceful restart"
      [ "$p" = sk ] && for b in $(pgrep -f "^bash -c python3 -u council_docs.py sk run"); do kill -TERM $b; done
      kill -TERM $pid
      for i in $(seq 1 90); do kill -0 $pid 2>/dev/null || break; sleep 10; done
      if kill -0 $pid 2>/dev/null; then log "$p pid $pid did not exit in 15 min; left running, not relaunched"; continue; fi
      case $p in
        sk) MALLOC_ARENA_MAX=2 setsid nohup bash -c "python3 -u council_docs.py sk run --workers 10 >> $L/council_sk.nohup.out 2>&1; python3 -u council_docs.py at run --workers 8 >> $L/council_at.nohup.out 2>&1" > /dev/null 2>&1 < /dev/null & ;;
        cz) MALLOC_ARENA_MAX=2 setsid nohup python3 -u council_docs.py cz run --workers 12 >> $L/council_cz.nohup.out 2>&1 < /dev/null & ;;
        at) MALLOC_ARENA_MAX=2 setsid nohup python3 -u council_docs.py at run --workers 8 >> $L/council_at.nohup.out 2>&1 < /dev/null & ;;
      esac
      sleep 5; log "$p relaunched: $(pgrep -f "^python3 -u council_docs.py $p run" | tr '\n' ' ')"
    fi
  done
  if [ $any = 0 ] && ! pgrep -f "^bash -c python3 -u council_docs.py sk run" > /dev/null; then idle=$((idle+1)); else idle=0; fi
  [ $idle -ge 30 ] && { log "no council runs for 30 min; guard exits"; exit 0; }
  sleep 60
done
