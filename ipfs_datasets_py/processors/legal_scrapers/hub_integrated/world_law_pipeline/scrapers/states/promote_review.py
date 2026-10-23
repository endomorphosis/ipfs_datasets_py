#!/usr/bin/env python3
"""Promote reviewed files for a source from staging/states/_review/ and mark them staged. Usage: promote_review.py <source_key>"""
import sys, glob, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import promote, STAGING
key = sys.argv[1]
for p in sorted(glob.glob(str(STAGING / "_review" / "*" / f"*.{key}-*.jsonl"))):
    ids = [json.loads(l)["doc_id"] for l in open(p, encoding="utf-8")]
    d = promote(p)
    with open(STAGING / "_state" / f"{key}.done.tsv", "a") as f:
        for i in ids:
            f.write(f"{i}\tstaged\t{d.name}\n")
    print(d, len(ids))
