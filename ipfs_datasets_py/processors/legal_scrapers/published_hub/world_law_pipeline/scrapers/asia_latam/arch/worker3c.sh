#!/bin/bash
# worker 3 continuation (lane stays at <=3 archive workers): after AU/ZA sites (pid 3490756):
# ES BOPs (first 1500 PDFs) -> MX Orden Juridico (~2k docs) -> ES rest -> Peru PDFs hourly loop
cd "$(dirname "$0")"
PY=/workspace/world_law/pipeline/venv/bin/python
while kill -0 3490756 2>/dev/null; do sleep 30; done
$PY -u es_arch.py --max-fetch 1500
$PY -u mx_arch.py
$PY -u es_arch.py
$PY -u pe_pdf.py --loop 3600
