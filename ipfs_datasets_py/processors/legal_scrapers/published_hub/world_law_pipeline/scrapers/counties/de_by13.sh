#!/bin/sh
# 2026-10-24 de_by13: the 2 Bavarian Landkreise never staged by de_by..de_by12 (all 71 checked against de_by*_entries/.sh, _logs, processed/counties/DE,
#  staging/web/DE source_urls): Forchheim (Q10445) and Fürth (Q10455); both were "no_archived_index" in de_by11 archive-only.
#  live crawl (de_kreisrecht_build, robots RFC 9309): Forchheim - lra-fo.de reachable again; server sends the wrong intermediate, so SSL_CERT_FILE =
#     system CAs + public DigiCert "Thawte TLS RSA CA G1" (from cacerts.digicert.com, issued by DigiCert Global Root G2; verification stays ON).
#     robots.txt allows /loadDocument.phtml (only /output/, /cache/, search disallowed). Amtsblatt index: 100 PDFs. Test 4/4 OK (de_by13_test.log).
#  archive-only (archive_retry, CC/Wayback only): Fürth - landkreis-fuerth.de robots.txt = Cloudflare 403 (unreachable). Config built by
#     de_by13_cdx_cfg.py from the Wayback CDX PDF listing (law paths: Amtsblatt/Satzung/Verordnung/...): 658 URLs, none with query strings.
# Archive rounds idempotent (archive_retry skips staged source_urls), 30 min apart, max 40 min each (flush before outer timeout). Disk guard 45 GB.
cd /workspace/world_law/pipeline/scrapers/counties
L=/workspace/world_law/staging/counties/_logs; PY=/workspace/world_law/pipeline/venv/bin/python
g() { df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }; }
g; echo "$(date) start live crawl Forchheim"; SSL_CERT_FILE=$PWD/_cabundle/de_by13_lrafo_bundle.pem $PY -u de_kreisrecht_build.py de_by13_entries.json by_kreisrecht 400; echo "$(date) live crawl done"
# Fürth archive phase only if its test batch (de_by13_test_fuerth_archive.json, 3 URLs, de_by13_test_archive.log) staged >=1 doc
while pgrep -f "archive_retry.py de_by13_test_fuerth_archive.json" >/dev/null; do sleep 60; done
grep -qE "^written: .* staged [1-9]" $L/de_by13_test_archive.log || { echo "$(date) Fürth archive test did not pass (no doc staged) - archive phase skipped"; tail -n 1 $L/de_by13_test_archive.log; exit 0; }
echo "$(date) Fürth archive test passed: $(grep -E '^written' $L/de_by13_test_archive.log)"
for round in 1 2 3 4 5 6 7 8; do
  for c in de_by_kreisrecht_landkreis_fürth_archive.json; do
    g; echo "== archive round $round $c $(date)"; timeout 3000 $PY -u archive_retry.py $c 40 2>&1 | grep --line-buffered -E '^(todo|OK|MISS|INVALID|SKIP_NOTPDF|written)'
  done
  [ $round -lt 8 ] && sleep 1800
done
echo "$(date) done"
