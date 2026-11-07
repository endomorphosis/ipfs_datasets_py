#!/bin/sh
PY=/workspace/world_law/pipeline/venv/bin/python; [ -x "$PY" ] || PY=/usr/bin/python3   # venv missing after 2026-10-18 box restore
cd /workspace/world_law/pipeline/scrapers/ukie
export MALLOC_ARENA_MAX=2 ARCHIVE_LANE=ukie
$PY -u discover_parish_dns.py
echo DISCOVER_DNS_DONE_ALL
