#!/bin/bash
# Until the pre-hook SAPL process (pid $1) exits, re-scan local staged SAPL rows into the scanned-PDF queue every 30 min
# (rows staged by the old process are not queued by the new sapl.py hook). Exits once that pid is gone (one final pass).
cd "$(dirname "$0")"
while kill -0 "$1" 2>/dev/null; do
  python3 build_scanned_queue_local.py; sleep 1800
done
python3 build_scanned_queue_local.py; echo "$(date) old SAPL pid $1 gone -> bridge done"
