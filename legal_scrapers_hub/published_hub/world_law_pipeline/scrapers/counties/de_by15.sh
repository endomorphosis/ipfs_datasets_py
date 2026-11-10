#!/bin/sh
# 2026-10-26 16:12 PDT de_by15: Landkreis Bamberg (Q10444, Wikidata label "Landkreis Bamberg", P856 landkreis-bamberg.de). Copied from de_by14.sh (Aschaffenburg, same Advantic CMS).
#  Prior work: 2026-10-21 de_by (Amtsblatt index, 185 links, 3-URL test config only, nothing staged); de_by_archive no_archived_index. 0 Q10444 docs in staging/processed/quarantine before this run.
#  robots.txt (RFC 9309) disallows only /cache/, /output/, suche/suchen, redirect, showobject -> loadDocument.phtml allowed live; 3 /output/ links go via us_pdf_list's archive path.
#  exclude_re drops the Radverkehr "Links-Downloads" HTML page. Test 16:05-16:09 PDT (de_by15_test.log): 3/3 OK, text PDFs, doc_ids carry ~URL-hash suffix. Index: 60 pages, 184 links (183 after exclude).
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live crawl Bamberg"; $PY -u de_kreisrecht_build.py de_by15_entries.json by_kreisrecht 400; echo "$(date) done"
