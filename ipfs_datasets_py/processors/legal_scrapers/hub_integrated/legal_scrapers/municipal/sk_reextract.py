#!/usr/bin/env python3
"""Re-extract raw records whose document was RTF or legacy .doc (collected before LibreOffice support) or HTML (re-decoded with the page charset, e.g. windows-1250) from the fetch cache.
Usage: sk_reextract.py RAW/raw/x.jsonl [...]   (rewrites in place; counts printed)"""
import json, sys, os, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sk_common import CACHE, doc_text, clean
for fn in sys.argv[1:]:
    recs = [json.loads(l) for l in open(fn)]; n = miss = 0
    for r in recs:
        ex = r["extras"]
        if ex.get("extraction") in ("text", "doc-binary-unsupported", "html") or r["text"].startswith("{\\rtf"):
            c = os.path.join(CACHE, hashlib.sha1(r["source_url"].encode()).hexdigest())
            if not os.path.exists(c): miss += 1; continue
            t, how = doc_text(open(c, "rb").read(), json.load(open(c + ".json")))
            r["text"] = clean(t); ex["extraction"] = how; n += 1
    with open(fn, "w") as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(fn, "reextracted", n, "missing_cache", miss, flush=True)
