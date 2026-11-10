#!/bin/bash
# worker 3 continuation v2 (coordinator 2026-10-10: Peru CDN dropped from the chain, Chile stays dropped):
# after AU/ZA sites: ES BOPs (first 1500 PDFs) -> MX Orden Juridico -> ES rest.
# Clean stop: touch _archive_work/_STOP_worker3d (chain stops after/between steps) plus the running step's
# _archive_work/<job>/_STOP. A fresh launch clears _STOP_worker3d.
cd "$(dirname "$0")"
export ARCHIVE_LANE=asia_latam  # box-wide limiter fair-share lane (archive/README.md)
PY=/workspace/world_law/pipeline/venv/bin/python
CS=/workspace/world_law/staging/asia_latam/_archive_work/_STOP_worker3d
rm -f "$CS"
step() { [ -e "$CS" ] && { echo "$(date) chain _STOP -> exit"; exit 0; }; echo "$(date) start: $*"; "$@"; }
while pgrep -f "^$PY -u sites_arch.py" >/dev/null; do [ -e "$CS" ] && exit 0; sleep 30; done
step $PY -u es_arch.py --max-fetch 1500
step $PY -u mx_arch.py
step $PY -u es_arch.py
echo "$(date) chain done"
