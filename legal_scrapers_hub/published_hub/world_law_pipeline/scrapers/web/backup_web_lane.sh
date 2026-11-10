#!/usr/bin/env bash
# Backs up the World Law Web Crawler lane (code, tests, small state files) to the persistent store.
# Never copies bulk staged docs (_raw, places/, robots/, *.sqlite, logs). Uses rsync if present, else cp -u.
set -uo pipefail
DST=${DST:-/cursor/stores/store-0a6fe626-8402-4178-a99b-322da90e0519/world_law_web}
WL=/workspace/world_law
[ -d "$(dirname "$DST")" ] || { echo "$(date) store missing"; exit 1; }
mkdir -p "$DST/code" "$DST/tools" "$DST/state"
cp_tree() { # src_dir dst_dir [find predicates...]
  local s=$1 d=$2; shift 2
  (cd "$s" && find . "$@" -type f -size -200M -print0 | xargs -0 -r cp -u --parents -t "$d")
}
cp_tree $WL/pipeline/scrapers/web "$DST/code" -not -path '*/__pycache__/*'
cp -u $WL/pipeline/tools/old_url_check.py "$DST/tools/"
cp_tree $WL/staging/web "$DST/state" \( -path '*/_raw/*' -o -path '*/_logs/*' -o -path '*/_state/places/*' -o -path '*/_state/robots*' -o -name '*.sqlite' -o -name '*.tmp' \) -prune -o \
  \( -name '_progress.json' -o -name '*.pid' -o -name current_lane -o -name DONE -o -name 'done*.jsonl' -o -name done_place_ids.txt \
     -o -name place_results.jsonl -o -path './_requeue/lists/*' -o -path './_discovery/*' -o -path './_queue/*' \
     -o -path './DE/_archive_work/*.jsonl' -o -path './DE/_archive_work/*.tsv' -o -name '*robots_audit.json' \)
cp -u $WL/state/web_restore/published_place_keys.tsv "$DST/state/" 2>/dev/null
echo "$(date '+%F %T %Z') backup ok $(du -sh "$DST" | cut -f1) $(find "$DST" -type f | wc -l) files"
