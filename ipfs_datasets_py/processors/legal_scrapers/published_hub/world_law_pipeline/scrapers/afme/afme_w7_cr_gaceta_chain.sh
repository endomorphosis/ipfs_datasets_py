#!/bin/bash
# wave 7: CR La Gaceta municipal sections 2016-01-01..2026-10-16 (test 46/46 ok, 0 bad) -> stage. Restartable (day cache afme/_cr_gaceta/).
# afme_cr_gaceta.py exits 3 when its RSS passes 300 MB (bs4 growth); the loop restarts it from the day cache.
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_wave7.log
echo "$(date) CR gaceta full start" >> $L
while :; do
  .afme_venv/bin/python -W ignore afme_cr_gaceta.py 2016-01-01 2026-10-16 >> afme/_cr_gaceta_full.log 2>&1; rc=$?
  [ $rc -eq 3 ] || break; echo "$(date) CR gaceta self-restart (rss) at $(ls afme/_cr_gaceta | wc -l) days" >> $L; sleep 5
done
echo "$(date) CR gaceta full rc=$rc $(tail -1 afme/_cr_gaceta_full.log | head -c 400)" >> $L
[ $rc -eq 0 ] && .afme_venv/bin/python afme_stage.py >> $L 2>&1; echo "$(date) CR gaceta chain DONE" >> $L
