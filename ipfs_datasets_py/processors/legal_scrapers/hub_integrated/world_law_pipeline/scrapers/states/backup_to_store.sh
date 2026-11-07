#!/bin/bash
: "${WORLD_LAW_ROOT:=$HOME/.ipfs_datasets/world_law}"
# Hourly small backup of states-lane code + checkpoints (no big logs / raw _work).
STORE=/cursor/stores/store-7a39b3fc-9a2e-4099-a192-e1bc4d4efc77
if [ -d "$STORE" ] && [ -w "$STORE" ]; then DST=$STORE/states_backup; else DST=${WORLD_LAW_ROOT}/state/backups/states_backup_FALLBACK_samedisk; fi
mkdir -p "$DST/code" "$DST/state"
W=${WORLD_LAW_ROOT}
(cd $W/pipeline/scrapers/states && find . -path ./data -prune -o -type f -size -20M ! -name "*.pyc" -print | cpio -pdmu --quiet "$DST/code/" 2>/dev/null || tar --exclude=./data -cf - . | tar -xf - -C "$DST/code/")
cd $W/staging/states && find . -path ./_logs -prune -o -type f -size -20M \( -name "*.tsv" -o -name "*queue*" -o -name "*.json" \) -print | while read f; do mkdir -p "$DST/state/$(dirname "$f")"; cp -p "$f" "$DST/state/$f"; done
date -u +%FT%TZ > "$DST/LAST_BACKUP"; echo "backup -> $DST ($(du -sh "$DST"|cut -f1))"
