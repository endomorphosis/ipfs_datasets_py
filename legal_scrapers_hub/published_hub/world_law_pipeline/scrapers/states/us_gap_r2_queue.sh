#!/bin/bash
# 2026-10-26 09:18 PDT: r2 tests (held in _review) after r1 batches were rejected by eye:
#  AK r1 cp1252 smart quotes/dashes decoded as latin-1 (C1 mojibake) -> utf-8/cp1252 decode;
#  ME r1 per-page header/footer frames -> _me_strip_frames + terms_restrict_reuse tag (Maine copyright claim);
#  SD r1 12/20 no_sections (relative DisplayStatute.aspx?...&Statute= links missed) -> regex accepts both link forms.
cd /workspace/world_law/pipeline/scrapers/states
. ./lane_ramgate.sh
L=/workspace/world_law/staging/states/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
for k in us_sd_sdcl us_me_mrs us_ak_statutes; do
  echo "$(date) test $k r2"; ramgate_run 150 $L/test_${k}_r2.out $PY -u run_full.py --source $k --test 20; echo "$(date) test $k r2 rc=$?"
done
echo "$(date) GAPR2_END"
