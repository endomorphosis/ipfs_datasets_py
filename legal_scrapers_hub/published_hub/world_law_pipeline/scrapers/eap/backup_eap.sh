#!/bin/bash
# backup eap code + checkpoints (not bulk data) to persistent store; rsync if available, else cp
D=/cursor/stores/store-da77f335-24a8-4157-95c4-3621f1a6f7b0/eap_backup
S=/workspace/world_law/pipeline/scrapers/eap; W=/workspace/world_law/staging/eap/_eap_work
[ -d "$D" ] || exit 0
mkdir -p $D/scripts $D/eap_work
if command -v rsync >/dev/null; then
  rsync -a --exclude .venv --exclude __pycache__ $S/ $D/scripts/
  rsync -a --prune-empty-dirs --exclude='hub/***' --include='*/' --include='*ckpt*' --include='*.done' --include='*.FINISHED*' --include='*.json' --include='*.tsv' --include='*.csv' --include='*.miss' --include='*.retry_at' --include='*.unmapped' --include='*manifest*.jsonl' --include='*.txt' --exclude='*' $W/ $D/eap_work/
else
  (cd $S && find . -path ./.venv -prune -o -type f -print | xargs -d '\n' cp --parents -u -t $D/scripts/)
  (cd $W && find . -path ./hub -prune -o -type f \( -name '*.done' -o -name '*.FINISHED*' -o -name '*.json' -o -name '*.tsv' -o -name '*.csv' -o -name '*.miss' -o -name '*.retry_at' -o -name '*.unmapped' -o -name '*manifest*.jsonl' -o -name '*.txt' \) -print | xargs -d '\n' cp --parents -u -t $D/eap_work/) 2>/dev/null
fi
date '+%F %T' > $D/LAST_BACKUP
