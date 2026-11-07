#!/bin/bash
# CH LexFind 20-row tests (held in _review) for ZH (de), GE (fr), TI (it), GR (de/it/rm)
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
for c in zh ge ti gr; do
  /workspace/world_law/pipeline/venv/bin/python run_full.py --source ch_lexfind_$c --test 20 > $L/test_ch_lexfind_$c.out 2>&1
done
