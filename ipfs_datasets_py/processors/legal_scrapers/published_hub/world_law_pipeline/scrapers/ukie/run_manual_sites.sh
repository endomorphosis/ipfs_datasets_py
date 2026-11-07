#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
# (c) principal councils whose site was missing from the candidate list (Newcastle upon Tyne, City of Edinburgh),
# plus a --refresh of Orkney and Shetland with the topic-section crawl; archive for robots-disallowed docs.
cd /workspace/world_law/pipeline/scrapers/ukie
S=/workspace/world_law/staging/ukie/_state
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
. ./archive_passes.sh
$PY -u councils.py run --no-archive --places wd:Q21012735,wd:Q2379199
$PY -u councils.py run --no-archive --refresh --places wd:Q100166,wd:Q47134
$PY -u councils.py run --archive-queue --archive-docs 8 --places-file $S/manual_sites_places.txt
archive_later_passes $S/manual_sites_places.txt 6
echo MANUAL_SITES_DONE
