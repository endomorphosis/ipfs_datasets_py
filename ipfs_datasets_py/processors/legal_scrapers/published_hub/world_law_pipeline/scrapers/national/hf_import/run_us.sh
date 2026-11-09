#!/bin/bash
cd /workspace/world_law/staging/national/_hf_import
export OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2 HF_HUB_DISABLE_TELEMETRY=1
for k in usc states; do nice -n 10 prlimit --as=3500000000 /workspace/hf-venv/bin/python /workspace/world_law/pipeline/scrapers/national/hf_import/hf_import_us.py $k || [ $? -ne 3 ] || exit 3; done
echo US_DONE
