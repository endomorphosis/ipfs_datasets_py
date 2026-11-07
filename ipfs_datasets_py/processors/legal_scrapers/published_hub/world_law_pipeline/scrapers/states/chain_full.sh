#!/bin/bash
# chain_full.sh TARGET CC TESTPID FULLARGS... : wait for the review test, QC-promote its files, then run the full crawl.
T=$1; CC=$2; PID=$3; shift 3
cd /workspace/world_law/pipeline/scrapers/states
while kill -0 $PID 2>/dev/null; do sleep 60; done
echo "$(date) test $T finished; QC"
TAG=$(../../venv/bin/python -c "import sys;sys.path.insert(0,'.');import arch_states,$T;print($T.Adapter.tag)")
../../venv/bin/python qc_promote.py "/workspace/world_law/staging/states/_review/$CC/*.$TAG-*.jsonl"
echo "$(date) starting full $T $*"
export ARCHIVE_LANE=states
exec ../../venv/bin/python -u arch_states.py $T "$@"
