#!/bin/sh
# 2026-10-26 18:10 PDT: Bamberg (Q10444) archive pass 1 for the 2 de_by15 failures (config de_by_kreisrecht_landkreis_bamberg_archive.json):
#  both /output/download.php (robots-disallowed live -> archive only), ArchiveDeferred (CC busy / Wayback cooldown) -> retryable.
#  fid=2892.850.1 "Telefonnummern zur Terminvereinbarung im Überblick", fid=2976.5143.1 "Telefonverzeichnis Landratsamt Bamberg - komplett" (phone lists, not law; Normalizer may drop).
#  Chained: waits for Aschaffenburg archive pass 1 (PID 158680, which itself waits for Fürth pass 4 PID 36297) so only one archive_retry runs at once.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
. /workspace/world_law/pipeline/scrapers/counties/county_chain_guard.sh   # disk guard 46080 MiB (2026-10-26 21:20)
echo "$(date) restart after 2026-10-26 20:10 disk-kill; PID waits removed (36297/158680 dead); chained by county_chain_20261026.sh"
for round in 1 2 3; do
  g; echo "== archive round $round $(date)"; timeout 1800 $PY -u archive_retry.py de_by_kreisrecht_landkreis_bamberg_archive.json 25 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written|STOP|Traceback|[A-Za-z]*Error)'
  [ $round -lt 3 ] && sleep 600
done
echo "$(date) done"
