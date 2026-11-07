#!/bin/bash
# Resumable Wayback pass. Pass 1: cap PH_WB_MAXDOCS (25) docs/place, capped places -> _state/wayback_capped.jsonl.
# Pass 2 (auto, only if pass 1 exits 0 = finished): remaining docs of capped places (checkpoint wayback_done_pass2.jsonl).
# Stop cleanly: kill -TERM <python pid> (flushes, exits 143, no chaining).
cd /workspace/world_law/pipeline/scrapers/ph
export ARCHIVE_LANE=ph
/workspace/world_law/pipeline/venv/bin/python -W ignore wayback_pass.py; rc=$?
echo "$(date -u +%FT%TZ) pass1 exit $rc"
[ $rc -eq 0 ] || exit $rc
exec /workspace/world_law/pipeline/venv/bin/python -W ignore wayback_pass.py --second-pass
