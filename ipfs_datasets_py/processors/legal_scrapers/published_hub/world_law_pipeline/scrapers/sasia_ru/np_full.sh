#!/bin/bash
# discovery (checkpointed) then full Nepal run (checkpointed)
cd /workspace/world_law/staging/sasia_ru/_np
python3 /workspace/world_law/pipeline/scrapers/sasia_ru/np_match.py >> np_match.log 2>&1 || exit 1
echo "$(date '+%F %H:%M PT') discovery done: $(wc -l < np_places_full.jsonl) places" >> ../_ru/PROGRESS.md
exec python3 /workspace/world_law/pipeline/scrapers/sasia_ru/np_palika.py np_places_full.jsonl --cap 100000 --workers 8 >> np_full.log 2>&1
