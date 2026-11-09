#!/bin/bash
# Hourly backup of national-lane code + checkpoints. Never deletes anything at the destination.
# Uses rsync (no --delete) when available, else cp -a -u.
STORE=/cursor/stores/store-87c9065b-7ff1-4d07-87d9-ea1bfcabf337
if [ -d "$STORE" ] && [ -w "$STORE" ]; then DST=$STORE/national_backup; else DST=/workspace/world_law/state/backups/national_backup_FALLBACK_samedisk; fi
W=/workspace/world_law; S=$W/staging/national
mkdir -p "$DST/code" "$DST/state"
copy() { # src_dir dst_dir find-args...
  local src=$1 dst=$2; shift 2
  (cd "$src" && find . "$@" -print0 | while IFS= read -r -d '' f; do mkdir -p "$dst/$(dirname "$f")"; if command -v rsync >/dev/null; then rsync -a "$f" "$dst/$f"; else cp -a -u "$f" "$dst/$f"; fi; done)
}
copy $W/pipeline/scrapers/national "$DST/code/scrapers_national" -type f -size -20M ! -name "*.pyc"
copy $W/pipeline "$DST/code/pipeline_top" -maxdepth 1 -type f -size -20M
copy $S "$DST/state/staging_national" -type f -size -50M \( -name "_emitted_ids.txt" -o -name "*.tsv" -o -name "*.state.json" -o -name "*ckpt*" -o -name "*.done" -o -name "*queue*" -o -name "_*.json" -o -name "*.md" -o -name "*.csv" \) -not -path "*/_hf_import/*"
date -u +%FT%TZ > "$DST/LAST_BACKUP"; echo "$(date '+%F %T %Z') backup -> $DST ($(du -sh "$DST"|cut -f1))"
