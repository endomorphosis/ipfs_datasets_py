#!/bin/bash
# wave 10 chain NZ: live council bylaw crawl (afme_live10.py; resumable via afme/NZ/_au_done.tsv) -> stage NZ. Test passed 2026-10-20 (45 rows / 5 files / 0 bad).
cd /workspace/world_law/out; export ARCHIVE_LANE=afme; L=afme/_w10_chain.log
./afme_slot.sh x .afme_venv/bin/python -W ignore afme_live10.py afme/nz_w10_cfg.json 0 >> afme/_nz_w10_full.log 2>&1
echo "$(date) NZ crawl exit $?" >> $L
.afme_venv/bin/python afme_stage.py NZ >> afme/_stage_w10.log 2>&1
echo "$(date) NZ staged" >> $L
