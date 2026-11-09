#!/bin/bash
# 2026-11-01 19:25 PST: list-only build for 11 Bavarian Landkreise. max_urls=0 => de_kreisrecht_topup_build.py writes
# de_by_kreisrecht_<slug>_topup.json cfgs (titles = not-yet-staged PDFs) and us_pdf_list.py fetches nothing; then convert to entries/de_by_wd_Q*.json
cd /workspace/world_law/pipeline/scrapers/counties
PY=/workspace/world_law/pipeline/venv/bin/python
$PY -u de_kreisrecht_topup_build.py de_by_topup2_entries.json by_kreisrecht 0
$PY - <<'P'
import json, glob
from pathlib import Path
names = {e["name"] for e in json.load(open("de_by_topup2_entries.json"))}
for f in glob.glob("de_by_kreisrecht_*_topup.json"):
    c = json.load(open(f))
    if c.get("place_name") not in names or Path(f).stat().st_mtime < Path("de_by_topup2_entries.json").stat().st_mtime: continue
    out = dict(place_id=c["place_id"], country_code="DE", source_platform="de_by_kreisrecht", source_org=c["source_org"], doc_id_prefix="",
               language="de", doc_type="ordinance", place_name=c["place_name"], admin_level="landkreis", qid=c["qid"],
               items=[{"url": u, "title": t} for u, t in c["titles"].items()])
    p = f"entries/de_by_{c['place_id'].replace(':','_')}.json"; json.dump(out, open(p, "w"), ensure_ascii=False)
    print("ENTRIES", p, c["place_name"], len(out["items"]))
P
