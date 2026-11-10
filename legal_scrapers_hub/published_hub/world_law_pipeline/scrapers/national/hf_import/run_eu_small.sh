#!/bin/bash
# Retry EU import in smaller parts (32 MB), looping past MemoryError; stops on completion, disk-low (exit 3), STOP file, or 40 passes.
cd /workspace/world_law/staging/national/_hf_import
export OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2 HF_HUB_DISABLE_TELEMETRY=1 HF_MAX_BYTES=$((32<<20)) HF_MAX_DOCS=500
for i in $(seq 1 40); do
  [ -f STOP ] && { echo "STOP file present"; exit 0; }
  python3 -c "import json,sys;sys.exit(0 if json.load(open('state/EU.json')).get('complete') else 1)" && { echo EU_COMPLETE; exit 0; }
  echo "pass $i $(date)"
  nice -n 10 prlimit --as=4000000000 /workspace/hf-venv/bin/python /workspace/world_law/pipeline/scrapers/national/hf_import/hf_import.py EU
  [ $? -eq 3 ] && { echo "disk low, stopping"; exit 3; }
  sleep 5
done
echo EU_LOOP_END
