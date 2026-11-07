#!/bin/sh
# usage: chain_after.sh <pid> <script.py> <logname>  -- waits for <pid> (a catalog run) to exit, then runs "<script.py> all" detached-style
P=$1; S=$2; L=$3
while kill -0 "$P" 2>/dev/null; do sleep 60; done
cd /workspace/world_law/pipeline/scrapers/eu && MALLOC_ARENA_MAX=2 exec python3 -u "$S" all >> "/workspace/world_law/staging/eu/_logs/$L.nohup.out" 2>&1 < /dev/null
