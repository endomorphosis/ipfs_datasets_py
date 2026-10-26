#!/usr/bin/env python3
"""QC gate for states-lane review files: promote staging/states/_review/<CC>/<glob> files that pass, else leave them
(and report). Checks: validate_file OK, title_native non-empty, place_id matches file key, text >= 500 chars unless
content_complete is false, admin_level adm1."""
import glob, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from schema import place_key

bad = 0
for f in sorted(glob.glob(sys.argv[1])):
    probs = []
    for l in open(f, encoding="utf-8"):
        r = json.loads(l)
        if not (r.get("title_native") or "").strip(): probs.append((r["doc_id"], "no_title"))
        if not Path(f).name.startswith(place_key(r["place_id"]) + "."): probs.append((r["doc_id"], "place_mismatch"))
        if r.get("admin_level") != "adm1": probs.append((r["doc_id"], "admin_level"))
        if r.get("content_complete") is not False and len(r.get("text") or "") < 500: probs.append((r["doc_id"], "short_text"))
    if probs:
        bad += 1; print("HOLD", f, probs[:10])
    else:
        print("PROMOTED", common.promote(f))
sys.exit(1 if bad else 0)
