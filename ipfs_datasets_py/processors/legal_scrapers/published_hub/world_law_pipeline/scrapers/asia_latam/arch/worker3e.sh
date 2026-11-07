#!/bin/bash
# Worker 3 chain v3 (2026-10-10 19:40 PT; Benjamin via coordinator): ordered by expected yield.
# MX Orden Juridico -> ES robots-disallowed BOPs (first 1500 PDFs) -> AU/ZA sites (rest) -> sedelectronica (top 300 hosts)
# -> ES network-blocked BOPs (1500) -> ES robots rest -> ES blocked rest -> sedelectronica rest.
# No Peru CDN, no Chile. Every step uses the shared ArchiveFetcher via arch_common (lane asia_latam).
# Clean stop: touch _archive_work/_STOP_worker3e (+ _archive_work/<job>/_STOP for the running step).
cd "$(dirname "$0")"
export ARCHIVE_LANE=asia_latam  # box-wide limiter fair-share lane (archive/README.md)
PY=/workspace/world_law/pipeline/venv/bin/python
CS=/workspace/world_law/staging/asia_latam/_archive_work/_STOP_worker3e
rm -f "$CS"
step() { [ -e "$CS" ] && { echo "$(date) chain _STOP -> exit"; exit 0; }; echo "$(date) start: $*"; "$@"; echo "$(date) end rc=$?: $*"; }
step $PY -u mx_arch.py
step $PY -u es_arch.py --set robots --max-fetch 1500 --max-kb 3000
step $PY -u sites_arch.py --targets au,za
step $PY -u sede_arch.py --max-hosts 300
step $PY -u es_arch.py --max-fetch 1500
step $PY -u es_arch.py --set robots --max-kb 3000
step $PY -u es_arch.py
step $PY -u sede_arch.py
echo "$(date) chain done"
