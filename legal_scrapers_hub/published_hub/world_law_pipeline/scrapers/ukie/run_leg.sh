#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# (c) full legislation.gov.uk run: all ukla feed pages, then local-SI title queries. Resumable.
cd /workspace/world_law/pipeline/scrapers/ukie
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
$PY -u legislation_uk.py ukla --pages 1-1100
$PY -u legislation_uk.py lsi --types uksi,wsi --queries "Permit%20Scheme,Parking%20Contraventions,Road%20Traffic%20Contraventions,Lane%20Rental,Bus%20Lane%20Contraventions,Moving%20Traffic,Electoral%20Changes,Structural%20Changes,Electoral%20Arrangements"
$PY -u legislation_uk.py lsi --types ssi --queries "Permitted%20Parking%20Area,Electoral%20Arrangements,Decriminalised%20Parking,Bus%20Lane%20Enforcement"
echo LEG_DONE
