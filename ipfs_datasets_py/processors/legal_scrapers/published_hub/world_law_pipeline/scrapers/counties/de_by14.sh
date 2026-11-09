#!/bin/sh
# 2026-10-26 14:25 PDT de_by14: Landkreis Aschaffenburg (Q10471). Never staged (0 docs in staging/processed counties/DE, staging/web/DE, staging/pdf):
#  de_by4 (2026-10-21) test failed 0/3 on HTTP 504 Gateway Time-out; de_by_archive had no_archived_index. Site reachable again 2026-10-26.
#  robots.txt (RFC 9309) disallows only /cache/, /output/, search, redirect, showobject -> loadDocument.phtml (302 -> /PDF/...) allowed live;
#  /output/ links (~35) go through us_pdf_list's archive path (CC/Wayback, source_policy archived_robots_disallowed).
#  Test 14:14-14:18 PDT (de_by14_test.log): 3/3 OK, text PDFs, doc_ids carry the ~URL-hash suffix (query-string URLs). Index: 60 pages, 382 PDF links.
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
df -P / | awk 'NR==2{exit ($4/1048576<45)}' || { echo "STOP disk $(date)"; exit 0; }
echo "$(date) start live crawl Aschaffenburg"; $PY -u de_kreisrecht_build.py de_by14_entries.json by_kreisrecht 400; echo "$(date) done"
