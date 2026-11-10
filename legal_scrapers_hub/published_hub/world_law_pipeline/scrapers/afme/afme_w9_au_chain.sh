#!/bin/bash
# wave 9 chain A: AU council local laws (live) -> stage. Resumable (afme/AU/_au_done.tsv checkpoint).
cd /workspace/world_law/out; export ARCHIVE_LANE=afme
./afme_slot.sh x .afme_venv/bin/python -W ignore afme_au_live.py afme/au_cfg.json 0 >> afme/_au_full.log 2>&1
.afme_venv/bin/python afme_stage.py AU >> afme/_stage_w9.log 2>&1
echo "$(date) chain A done" >> afme/_au_full.log
