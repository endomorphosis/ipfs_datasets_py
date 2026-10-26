#!/usr/bin/env python3
"""Re-download the Zürich AS PDFs listed in docs_zh.jsonl (polite, 1 req/s) into a cache dir for re-extraction."""
import json, os, sys, time, hashlib, requests
raw, cache = sys.argv[1], sys.argv[2]; os.makedirs(cache, exist_ok=True)
S = requests.Session(); S.headers["User-Agent"] = "world-laws-municipal-collector/0.1 (research; polite)"
for l in open(raw):
    d = json.loads(l); fn = os.path.join(cache, hashlib.sha1(d["source_url"].encode()).hexdigest() + ".pdf")
    if os.path.exists(fn): continue
    for i in range(3):
        try:
            r = S.get(d["source_url"], timeout=60)
            if r.status_code == 200 and r.content.startswith(b"%PDF"): open(fn, "wb").write(r.content); break
        except requests.RequestException: pass
        time.sleep(3)
    time.sleep(1)
print("done", len(os.listdir(cache)))
