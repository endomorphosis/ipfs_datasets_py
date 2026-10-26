#!/usr/bin/env python3
"""Stadt Zuerich Amtliche Sammlung PDFs via Common Crawl index (ranged reads only)."""
import sys, json, re
import os; sys.path.insert(0, os.environ.get("LEGAL_SCRAPERS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
import common_crawl_helper as cc
COLS = ["CC-MAIN-2026-30","CC-MAIN-2026-21","CC-MAIN-2026-17","CC-MAIN-2026-08","CC-MAIN-2025-51","CC-MAIN-2025-47"]
p = []
for pre in ["/dam/web/de/politik-verwaltung/politik-recht/amtliche-sammlung", "/content/dam/web/de/politik-verwaltung/politik-recht/amtliche-sammlung",
            "/content/dam/stzh/portal/deutsch/amtliche-sammlung", "/dam/stzh/portal/deutsch/amtliche-sammlung"]:
    p += cc.find_pointers("www.stadt-zuerich.ch", COLS, status="200", mime_regex="pdf", path_prefix=pre,
                          max_records=5000, max_blocks_per_collection=40, include_subdomains=False)
best = {}
for x in p:
    m = re.search(r"amtliche-sammlung/.*?([^/]+\.pdf)", x["url"])
    if not m: continue
    best.setdefault(x["url"], x)
print(len(p), len(best))
json.dump(list(best.values()), open("/tmp/zh_ptrs.json", "w"))
