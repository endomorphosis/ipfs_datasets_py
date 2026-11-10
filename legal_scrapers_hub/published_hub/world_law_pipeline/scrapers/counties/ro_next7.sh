#!/bin/sh
# 2026-10-23 ro_next7: continuation of capped (MAXU 400) RO county runs from their saved found-lists, filtered to adopted HCJ only
# (keep hcj|hot*.pdf|hotărâre|/H###_; drop proiect/anex/anunț/declarații/minute/procese/dispoziții/rapoarte/spreadsheets). Remaining un-done judete
# (Bistrița-Năsăud, Brașov, Iași, Neamț, Olt, Prahova, Suceava, Vâlcea, Covasna) are behind bot-verification / robots fetch failure -> archive-only candidates.
# us_pdf_list skips URLs already staged/processed. Disk guard 45 GB (also inside us_pdf_list).
cd /workspace/world_law/pipeline/scrapers/counties
L=/workspace/world_law/staging/counties/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
for s in botoșani buzău ialomița; do
  df -P /workspace | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk"; exit 0; }
  echo "$(date) start $s"; $PY -u us_pdf_list.py ro_next7_${s}_rest.json > $L/ro_next7_${s}.log 2>&1; echo "$(date) $s $(tail -1 $L/ro_next7_${s}.log)"
done
echo "$(date) done"
