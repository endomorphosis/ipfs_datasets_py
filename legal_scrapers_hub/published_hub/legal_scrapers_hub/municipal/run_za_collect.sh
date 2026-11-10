#!/bin/bash
# ZA municipal supplement: one detached job, steps in sequence (resumable; re-run to continue).
# usage: ZA_STATE=<state dir> bash run_za_collect.sh
set -u
PY=${PY:-/workspace/ipfs_datasets_fresh_venv/bin/python}
D=$(cd "$(dirname "$0")" && pwd)
cd "$ZA_STATE"
echo "$(date -u +%FT%TZ) START openbylaws pid=$$"
$PY -W ignore "$D/collect_za_openbylaws.py"; echo "$(date -u +%FT%TZ) openbylaws rc=$?"
[ -e STOP_munisites ] && { echo STOP; exit 0; }
$PY -W ignore "$D/collect_za_munisites.py"; echo "$(date -u +%FT%TZ) munisites rc=$?"
[ -e STOP_munisites ] && { echo STOP; exit 0; }
$PY -W ignore "$D/collect_za_terms.py"; echo "$(date -u +%FT%TZ) terms rc=$?"
