#!/bin/bash
# CH cantons via LexFind, one canton after another (single process => 2 s/host politeness holds). Resumable: done.tsv per canton.
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
for c in zh be lu ur sz ow nw gl zg fr so bs bl sh ar ai sg gr ag tg ti vd vs ne ge ju; do
  /workspace/world_law/pipeline/venv/bin/python run_full.py --source ch_lexfind_$c >> $L/full_ch_lexfind_$c.out 2>&1
  echo "$(date -u +%FT%TZ) done $c" >> $L/ch_full.out
done
echo "$(date -u +%FT%TZ) ALL DONE" >> $L/ch_full.out
