#!/bin/bash
# Lane worker 3 (sequential, so the lane stays at <=3 archive workers): AU/ZA sites, then Peru PDFs (hourly loop).
cd "$(dirname "$0")"
PY=/workspace/world_law/pipeline/venv/bin/python
$PY -u sites_arch.py --targets au,za
$PY -u pe_pdf.py --loop 3600
