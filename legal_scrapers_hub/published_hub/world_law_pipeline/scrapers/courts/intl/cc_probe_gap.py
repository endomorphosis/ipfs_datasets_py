"""Gap-retry probe: Common Crawl CDX (+ optional Wayback CDX) for blocked court domains. Polite: single connection, 6s between calls,
exponential backoff on 503/429/TLS errors. Usage: cc_probe_gap.py OUT.jsonl CRAWL[,CRAWL] DOMAIN[,DOMAIN] [--wayback]"""
import json, time, urllib.request, sys
UA = "WorldCourtsResearchBot/1.0 (+public court directory research; polite crawl)"
out_p, crawls, doms = sys.argv[1], sys.argv[2].split(","), sys.argv[3].split(",")
WB = "--wayback" in sys.argv
def get(u, tries=int(__import__("os").environ.get("CC_TRIES", "4"))):
    d = 6
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=120)
            b = r.read().decode("utf-8", "replace"); time.sleep(6); return r.status, b
        except Exception as e:
            code = getattr(e, "code", 0)
            if code == 404: time.sleep(6); return 404, ""
            time.sleep(d); d *= 2; last = (code, str(e)[:120])
    return last
out = open(out_p, "a")
for dom in doms:
    for c in crawls:
        st, body = get(f"https://index.commoncrawl.org/{c}-index?url=*.{dom}&output=json&limit=5000")
        recs = []
        for l in (body.splitlines() if st == 200 else []):
            try: recs.append(json.loads(l))
            except ValueError: pass
        out.write(json.dumps({"src": "cc", "dom": dom, "crawl": c, "status": st, "err": None if st in (200, 404) else body, "n": len(recs), "recs": recs}) + "\n"); out.flush()
        print(dom, c, st, len(recs), flush=True)
    if WB:
        st, body = get(f"https://web.archive.org/cdx/search/cdx?url={dom}/*&output=json&limit=3000&filter=statuscode:200&collapse=urlkey", tries=2)
        try: rows = json.loads(body)[1:]
        except Exception: rows = []
        out.write(json.dumps({"src": "wayback", "dom": dom, "status": st, "n": len(rows), "rows": rows}) + "\n"); out.flush()
        print(dom, "wayback", st, len(rows), flush=True)
