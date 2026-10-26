#!/usr/bin/env python3
"""Restage single-purpose-authority acts so records carry issuing_body (Normalizer 2026-10-18)."""
import json, sys
sys.argv = [sys.argv[0]]
import legislation_uk as L
R = L.Run()
try:
    R.restage("ukla/2013/6", ["wd:Q21695028", "wd:Q175945"], "normalizer_remap_20261017")
    R.restage("ukla/2002/5", ["wd:Q213361"], "normalizer_remap_20261017")
finally:
    files = R.flush()
    print(json.dumps({"files": [f.rsplit('/', 1)[1] for f in files], **R.n}))
