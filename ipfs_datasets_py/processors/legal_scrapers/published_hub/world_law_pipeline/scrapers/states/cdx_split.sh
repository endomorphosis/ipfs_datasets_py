#!/bin/bash
# Split large Wayback CDX prefix queries into small sub-prefixes (URL discovery only; via the shared archive limiter, lane=states).
# usage: cdx_split.sh <out_file> <prefix_base> <suffix1> [suffix2 ...]
cd /workspace/world_law/pipeline
OUT="$1"; BASE="$2"; shift 2
PARTS=/workspace/world_law/pipeline/scrapers/states/data/cdx_parts
for s in "$@"; do
  key=$(echo "${BASE}${s}" | tr '/:' '__')
  [ -s "$PARTS/$key.txt" ] && continue
  ARCHIVE_LANE=states timeout 900 venv/bin/python -m archive --lane states --no-cc captures "${BASE}${s}" --match prefix --wb-collapse urlkey --limit 20000 > "$PARTS/.$key.tmp" 2>> "$PARTS/errors.log"
  rc=$?
  if [ $rc -eq 0 ]; then mv "$PARTS/.$key.tmp" "$PARTS/$key.txt"; [ -s "$PARTS/$key.txt" ] || echo "# empty" > "$PARTS/$key.txt"; else echo "$(date -u +%FT%TZ) FAIL rc=$rc ${BASE}${s}" >> "$PARTS/errors.log"; rm -f "$PARTS/.$key.tmp"; fi
done
cat "$PARTS"/$(echo "$BASE" | tr '/:' '__')*.txt 2>/dev/null | grep -v '^#' | sort -u > "$OUT"
echo "done $(wc -l < "$OUT") lines -> $OUT"
