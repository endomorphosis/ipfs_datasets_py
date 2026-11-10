#!/bin/bash
# Resume the CH canton chain after the 2026-10-18 box move (zh..tg finished; ti was at 500/603). Resumable per canton via done.tsv.
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
for c in ti vd vs ne ge ju; do
  /workspace/world_law/pipeline/venv/bin/python run_full.py --source ch_lexfind_$c >> $L/full_ch_lexfind_$c.out 2>&1
  echo "$(date -u +%FT%TZ) done $c" >> $L/ch_full.out
done
