#!/bin/bash
# usage: afme_w7_pdfgaz_chain.sh CC FROM TO NTEST  -- test (latest NTEST editions) -> gate ok>=min(15,files), 0 bad, >=1 file -> full -> stage. Slot-limited.
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave7.log; P=".afme_venv/bin/python -W ignore"; C=$1
grep -q '^DONE' afme/_pdfgaz_${C}_test.log 2>/dev/null || ./afme_slot.sh x $P afme_pdfgaz.py $C $2 $3 test $4 > afme/_pdfgaz_${C}_test.log 2>&1
t=$(grep '^DONE' afme/_pdfgaz_${C}_test.log); echo "$(date) $C pdfgaz test $t" >> $L
ok=$(echo "$t" | awk '{print $3}'); bad=$(echo "$t" | awk '{print $5}'); n=$(echo "$t" | awk '{print $7}'); need=$(( n<15 ? n : 15 ))
if [ -n "$ok" ] && [ "$ok" -ge 1 ] && [ "$ok" -ge "$need" ] && [ "$bad" -eq 0 ]; then
  ./afme_slot.sh x $P afme_pdfgaz.py $C $2 $3 > afme/_pdfgaz_${C}_full.log 2>&1
  echo "$(date) $C pdfgaz full $(grep '^DONE' afme/_pdfgaz_${C}_full.log)" >> $L; .afme_venv/bin/python afme_stage.py >> $L 2>&1
else echo "$(date) $C pdfgaz full NOT launched" >> $L; fi
