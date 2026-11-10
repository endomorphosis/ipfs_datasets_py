#!/bin/bash
# Third serial queue: Wayback CDX URL lists (PEI PDFs, AZ sections) via the shared archive module, then tests.
cd /workspace/world_law/pipeline/scrapers/states
L=/workspace/world_law/staging/states/_logs
PY=/workspace/world_law/pipeline/venv/bin/python
while pgrep -f "terms_queue2?.sh" >/dev/null; do sleep 30; done
mkdir -p data/archive
echo "$(date) cdx PEI"; $PY -u cdx_list.py data/archive/pe_pdf.txt "www.princeedwardisland.ca/sites/default/files/legislation/" "" > $L/cdx_pe_pdf.out 2>&1; echo "rc=$?"
echo "$(date) cdx AZ"; $PY -u cdx_list.py data/archive/az_ars.txt "www.azleg.gov/ars/" $(seq 1 49 | sed 's|$|/|') > $L/cdx_az_ars.out 2>&1; echo "rc=$?"
for k in ca_pe_pdf us_az_ars_archive; do
  [ -s data/archive/$( [ $k = ca_pe_pdf ] && echo pe_pdf || echo az_ars ).txt ] || continue
  echo "$(date) test $k"; $PY -u run_full.py --source $k --test 20 > $L/test_$k.out 2>&1
done
echo "$(date) QUEUE3_END"
