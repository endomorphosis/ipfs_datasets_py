#!/bin/sh
# 2026-10-26 16:16 PDT: Aschaffenburg (Q10471) archive pass 1 for the 36 de_by14 failures (config de_by_kreisrecht_landkreis_aschaffenburg_archive.json):
#  35 /output/download.php links (robots-disallowed live -> archive only) all ArchiveDeferred (CC busy / Wayback cooldown) -> retryable;
#  1 loadDocument.phtml FID=3984.2429.1 live "Remote end closed connection without response" -> archive copy (archived_live_fetch_failed).
#  Test 16:05-16:13 (de_by14_archive_test.log, 3 URLs, 8 min): 0 staged / 0 miss / 3 still deferred - Wayback breaker open box-wide while Fürth pass 4 runs.
#  So this waits for Fürth pass 4 (PID 36297) to exit before using the archive hosts, then same round pattern as de_by13_fuerth_archive_pass4.sh.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard 46080 MiB (2026-10-26 21:20)
echo "$(date) restart after 2026-10-26 20:10 disk-kill; PID waits removed (36297/158680 dead); chained by county_chain_20261026.sh"
for round in 1 2 3 4 5 6; do
  g; echo "== archive round $round $(date)"; timeout 3300 $PY -u archive_retry.py de_by_kreisrecht_landkreis_aschaffenburg_archive.json 50 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 6 ] && sleep 600
done
echo "$(date) done"
